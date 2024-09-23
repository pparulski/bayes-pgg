import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, make_response, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from models import db, Participant, save_participant_data, calculate_human_player_average, calculate_ai_player_average
from sqlalchemy import func
import requests
from openai import OpenAI
import numpy as np
import secrets
import time  # Ensure time is imported correctly
import datetime
import re


# Use the environment variable for OpenAI API key
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize the db instance and migrate
db = SQLAlchemy(app)  # Initialize the db once with the app
migrate = Migrate(app, db)  # Initialize Flask-Migrate with the app and db

# Game settings
initial_tokens = 10
total_games = 10  # Number of one-shot games in each session
total_sessions = 2  # Number of sessions


# Function to restore state from cookies
@app.before_request
def restore_state_from_cookies():
    if 'session_num' not in session:
        session['session_num'] = int(request.cookies.get('session_num', 1))
    if 'game' not in session:
        session['game'] = int(request.cookies.get('game', 1))

@app.route('/')
def welcome():
    # Capture Prolific PID and Session ID from URL parameters
    prolific_pid = request.args.get('PROLIFIC_PID')
    session_id = request.args.get('SESSION_ID')

    # Ensure Prolific PID and Session ID are captured
    if prolific_pid and session_id:
        session['prolific_pid'] = prolific_pid
        session['session_id'] = session_id
    else:
        # Handle the case where these parameters are missing
        return "Missing Prolific PID or Session ID", 400

    # Check for cookies that store the last page, game, and session state
    last_page = request.cookies.get('last_page')
    game = request.cookies.get('game')
    session_num = request.cookies.get('session_num')

    # If cookies are set, restore the state
    if last_page and game and session_num:
        session['game'] = int(game)
        session['session_num'] = int(session_num)
        return redirect(url_for(last_page))

    return redirect(url_for('check_cookies'))

@app.route('/check_cookies')
def check_cookies():
    resp = make_response(redirect(url_for('show_welcome')))
    resp.set_cookie('test_cookie', 'test_value', max_age=3600)  # Expires in 1 hour
    return resp

@app.route('/cookies_required')
def cookies_required():
    return render_template('cookies_required.html')

@app.route('/show_welcome')
def show_welcome():
    # Assign a random participant ID if it does not exist
    if 'participant_id' not in session:
        session['participant_id'] = secrets.token_hex(8)

    # Initialize the start timestamp if it's not already set
    if 'start_timestamp' not in session:
        session['start_timestamp'] = datetime.datetime.now(datetime.UTC)  # Record the start timestamp
    return render_template('welcome.html')

@app.route('/instructions')
def instructions():
    resp = make_response(render_template('instructions.html'))

    # Set cookies for last visited page, game number, and session number
    resp.set_cookie('last_page', 'instructions', max_age=3600)
    resp.set_cookie('game', str(session.get('game', 1)), max_age=3600)  # Store game number
    resp.set_cookie('session_num', str(session.get('session_num', 1)), max_age=3600)  # Store session number
    
    return resp

@app.route('/start')
def start():
    # Randomly assign to control or experimental group
    if 'group' not in session:
        session['group'] = np.random.choice(['control', 'experimental'])
        print(f"Group assigned: {session['group']}")  # Log when group is assigned

    # Initialize session data only if it does not exist
    if 'session_num' not in session:
        session['session_num'] = 1
        session['game_history'] = []  # Initialize game history for this session
        session['contributions'] = []  # Initialize contributions list

    # Initialize other session-related variables
    session['game'] = 1  # Start from game 1
    session['intervention'] = False
    session['session_started'] = True

    return redirect(url_for('game'))

@app.route('/game')
def game():
    # Use session.get() without overwriting the session['game'] value
    game = session.get('game', 1)
    session_num = session.get('session_num', 1)

    # Render the game page with the correct session data
    resp = make_response(render_template('index.html', game=game, session_num=session_num))

    # Set cookies for last visited page, game number, and session number
    resp.set_cookie('last_page', 'game', max_age=3600)
    resp.set_cookie('game', str(game), max_age=3600)  # Store game number
    resp.set_cookie('session_num', str(session_num), max_age=3600)  # Store session number

    return resp

@app.route('/play/<int:contribution>', methods=['POST'])
def play(contribution):
    # Store the human contribution in the session
    session['current_contribution'] = contribution

    # Log the human contribution
    print(f"(Human) Contribution (Game {session['game']}, Session {session['session_num']}): {contribution}")

    # Add the contribution to the list
    if 'contributions' in session:
        session['contributions'].append(contribution)
    else:
        session['contributions'] = [contribution]

    # Redirect to the waiting page while the AI's move is being calculated
    return redirect(url_for('waiting'))

@app.route('/waiting')
def waiting():
    prolific_pid = session.get('prolific_pid')  # Retrieve from session
    session_id = session.get('session_id')      # Retrieve from session
    contribution = session.get('current_contribution', 0)

    # Retrieve INCOM values from session, default to None if not set
    incom_1 = session.get('incom_1', None)
    incom_2 = session.get('incom_2', None)
    incom_3 = session.get('incom_3', None)
    incom_4 = session.get('incom_4', None)
    incom_5 = session.get('incom_5', None)
    incom_6 = session.get('incom_6', None)

    game_num = session['game']
    session_num = session['session_num']
    participant_id = session['participant_id']
    group = session['group']

    # Check if this game has already been processed
    existing_entry = Participant.query.filter_by(
        participant_id=participant_id,
        session_num=session_num,
        round_num=game_num
    ).first()

    if existing_entry:
        print(f"Game {game_num} of session {session_num} for participant {participant_id} has already been processed. Skipping.")
        return redirect(url_for('outcome'))

    # Fetch game history for the current session only
    game_history = [game for game in session.get('game_history', []) if game['game_num'] <= total_games and game.get('session_num') == session_num]

    # Retrieve previous assistant messages from the session
    previous_messages = session.get('previous_messages', [])

    # Construct the new user message for the current round
    new_message = {
        "role": "user",
        "content": "\nHere's the history of your games with this player so far:\n"
    }

    for game_info in game_history:
        new_message['content'] += f"Game {game_info['game_num']}: Human contributed {game_info['human_contribution']}, You contributed {game_info['bot_contribution']}.\n"

    new_message['content'] += "\nIt's your move. Provide a number between 0 and 10 for your tokens contribution for this game. Do not provide justification, just a number."

    # Add the new user message to the conversation
    previous_messages.append(new_message)

    # If this is session 2 and the group is not 'control', add average contributions to the message
    if session_num == 2 and group != 'control':
        ai_avg_contribution = round(calculate_ai_player_average(participant_id), 1)
        historic_ai_avg_contribution = 8.1  # Replace with actual calculation if needed
        
        previous_messages.append({
            "role": "system",
            "content": (
                f"In the previous session, the AI's average contribution was {ai_avg_contribution}, "
                f"while the historic AI average contribution is {historic_ai_avg_contribution}."
            )
        })

    # System instructions (only needed once, placed before the conversation starts)
    system_message = {
        "role": "system",
        "content": (
            "You are playing a one-shot public goods game against a human. Each game, you receive 10 tokens. "
            "You can contribute between 0 and 10 tokens to a group account. If the total contribution of both players is 10 or more, "
            "the total contribution is multiplied by 1.5. The remaining tokens in your private account are added to half of the group account. "
            "Earnings from private and group accounts are summed up and form your game score. Your goal is to maximize your score."
            "Your goal is to maximize your score over 10 rounds by adapting to the human player's contributions."
            "Adjust your contribution dynamically based on the human's previous contributions."
        )
    }

    # Add the system message only once at the start
    if not session.get('system_message_added'):
        previous_messages.insert(0, system_message)  # Add it at the beginning of the conversation
        session['system_message_added'] = True  # Mark that the system message was added

    try:
        # Send the entire conversation history (few-shot prompting)
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=previous_messages
        )
        bot_contribution = int(completion.choices[0].message.content.strip())

        print(f"(API) AI Contribution (Game {game_num}, Session {session_num}): {bot_contribution}")

        # Calculate results
        total_contribution = contribution + bot_contribution
        if total_contribution >= 10:
            total_contribution *= 1.5

        private_account = 10 - contribution
        score = private_account + (total_contribution / 2)

        # Log game history
        game_history.append({
            'game_num': game_num,
            'human_contribution': contribution,
            'bot_contribution': bot_contribution,
            'score': score,
            'session_num': session_num  # Include session number in each game record
        })
        session['game_history'] = game_history

        session['participant_balance'] = score
        session['bot_contribution'] = bot_contribution

        # Save the updated assistant message to the conversation history
        previous_messages.append({
            "role": "assistant",
            "content": str(bot_contribution)
        })
        session['previous_messages'] = previous_messages  # Save the conversation in the session

        # Save the participant data as before
        save_participant_data(
            prolific_pid=prolific_pid,
            session_id=session_id,
            participant_id=participant_id,
            session_num=session_num,
            round_num=game_num,
            contribution=contribution,
            bot_contribution=bot_contribution,
            participant_balance=score,
            bot_balance=total_contribution - score,
            net_gain=score - private_account,
            group=group,
            start_timestamp=session.get('start_timestamp'),
            end_timestamp=None,
            incom_1=incom_1,
            incom_2=incom_2,
            incom_3=incom_3,
            incom_4=incom_4,
            incom_5=incom_5,
            incom_6=incom_6
        )

        # Redirect to outcome without incrementing game count here
        return redirect(url_for('outcome'))

    except Exception as e:
        print(f"Error occurred during API call: {e}")
        return redirect(url_for('outcome'))

@app.route('/outcome')
def outcome():
    prolific_pid = session.get('prolific_pid')  # Retrieve from session
    session_id = session.get('session_id')      # Retrieve from session

    # Retrieve INCOM values from session, default to None if not set
    incom_1 = session.get('incom_1', None)
    incom_2 = session.get('incom_2', None)
    incom_3 = session.get('incom_3', None)
    incom_4 = session.get('incom_4', None)
    incom_5 = session.get('incom_5', None)
    incom_6 = session.get('incom_6', None)
    # Get current game and session numbers
    game = session.get('game', 1)
    session_num = session.get('session_num', 1)
    participant_id = session['participant_id']

    # Check if the data for this game already exists in the database
    existing_entry = Participant.query.filter_by(
        participant_id=participant_id,
        session_num=session_num,
        round_num=game
    ).first()

    if not existing_entry:
        try:
            # If not exists, save the data as before
            save_participant_data(
                prolific_pid=prolific_pid,
                session_id=session_id,
                participant_id=participant_id,
                session_num=session_num,
                round_num=game,
                contribution=session.get('current_contribution', 0),
                bot_contribution=session.get('bot_contribution', 0),
                participant_balance=session.get('participant_balance', 10),
                bot_balance=session.get('bot_contribution', 0),
                net_gain=session.get('net_gain', 0),
                group=session.get('group'),
                start_timestamp=session.get('start_timestamp'),
                end_timestamp=None,
                incom_1=incom_1,  # Pass incom values
                incom_2=incom_2,
                incom_3=incom_3,
                incom_4=incom_4,
                incom_5=incom_5,
                incom_6=incom_6
            )
        except Exception as e:
            print(f"Unexpected error: {e}")
            return redirect(url_for('game'))  # Safely redirect to avoid errors

    # Remove any redundant logic here
    resp = make_response(render_template(
        'outcome.html',
        total_balance=session.get('participant_balance', 10),
        human_contribution=session.get('current_contribution', 0),
        bot_contribution=session.get('bot_contribution', 0),
        game=session['game'],
        session_num=session['session_num']
    ))
    
    # Set cookies for last visited page, game number, and session number
    resp.set_cookie('last_page', 'outcome', max_age=3600)
    resp.set_cookie('game', str(session.get('game', 1)), max_age=3600)  # Store game number
    resp.set_cookie('session_num', str(session.get('session_num', 1)), max_age=3600)  # Store session number
    
    return resp

@app.route('/continue_after_outcome')
def continue_after_outcome():
    session_num = session.get('session_num', 1)
    game = session.get('game', 1)

    # Check if we are at the end of Session 1
    if session_num == 1 and game == total_games:
        # Move to Session 2
        session['session_num'] = 2
        session['game'] = 1  # Reset game to 1 for the new session

        # Determine the next route (message or average_message) based on the group
        next_route = 'message' if session['group'] == 'control' else 'average_message'
        return redirect(url_for(next_route))

    # Check if we are at the end of Session 2
    elif session_num == 2 and game == total_games:
        # End of Session 2, redirect to the results
        return redirect(url_for('result'))

    # For games 1 to 9, or games in Session 2 before the last game
    else:
        session['game'] += 1  # Increment the game count
        return redirect(url_for('game'))  # Continue to the next game

@app.route('/result')
def result():
    participant_id = session['participant_id']
    session_num = session.get('session_num', 1)
    
    # Set the end timestamp at the time of result loading
    end_timestamp = datetime.datetime.now(datetime.UTC)

    # Update the end_timestamp in the database for each game of this participant
    games_to_update = Participant.query.filter_by(
        participant_id=participant_id,
        session_num=session_num
    ).all()

    for game in games_to_update:
        game.end_timestamp = end_timestamp

    db.session.commit()  # Commit all changes

    # Retrieve all games across both sessions (1 and 2)
    all_games = Participant.query.filter_by(participant_id=participant_id).all()

    # Calculate the total earnings in tokens across all games
    total_tokens_earned = sum(game.participant_balance for game in all_games)

    # Calculate the average earnings in tokens per game
    average_tokens_earned_per_game = total_tokens_earned / len(all_games) if all_games else 0

    # Convert the average earnings to USD (1 USD for 15 tokens, plus a base value of 1.58 USD)
    bonus = (average_tokens_earned_per_game / 15)
    earnings_in_usd = 1.58 + bonus

    # Round earnings to 2 decimal places for display
    earnings_in_usd = round(earnings_in_usd, 2)

    # Update the bonus field in the Participant records
    for game in games_to_update:
        game.bonus = bonus

    db.session.commit()  # Commit the bonus updates to the database

    # Calculate averages for AI and human player contributions for each session
    session_1_games = Participant.query.filter_by(participant_id=participant_id, session_num=1).all()
    session_2_games = Participant.query.filter_by(participant_id=participant_id, session_num=2).all()

    # Calculate the average contributions for session 1 and session 2
    session_1_human_avg_contribution = round(sum(game.contribution for game in session_1_games) / len(session_1_games), 1) if session_1_games else 0
    session_2_human_avg_contribution = round(sum(game.contribution for game in session_2_games) / len(session_2_games), 1) if session_2_games else 0
    session_1_ai_avg_contribution = round(sum(game.bot_contribution for game in session_1_games) / len(session_1_games), 1) if session_1_games else 0
    session_2_ai_avg_contribution = round(sum(game.bot_contribution for game in session_2_games) / len(session_2_games), 1) if session_2_games else 0

    # Render the results page with game history and earnings
    resp = make_response(render_template(
        'result.html',
        game_history=session.get('game_history', []),
        session_1_human_avg_contribution=session_1_human_avg_contribution,
        session_2_human_avg_contribution=session_2_human_avg_contribution,
        session_1_ai_avg_contribution=session_1_ai_avg_contribution,
        session_2_ai_avg_contribution=session_2_ai_avg_contribution,
        earnings_in_usd=earnings_in_usd
    ))

    # Set cookies for the last visited page, game number, and session number
    resp.set_cookie('last_page', 'result', max_age=3600)
    resp.set_cookie('game', str(session.get('game', 1)), max_age=3600)  # Store game number
    resp.set_cookie('session_num', str(session.get('session_num', 1)), max_age=3600)  # Store session number
    
    return resp

@app.route('/message')
def message():
    # Retrieve the current session number
    session_num = session.get('session_num', 1)

    # Display the transition message when moving from Session 1 to Session 2
    message = f"Session 1 is complete. You will now proceed to Session 2."

    # Set cookies for the current state
    resp = make_response(render_template('message.html', message=message))
    resp.set_cookie('last_page', 'message', max_age=3600)
    resp.set_cookie('game', str(session.get('game', 1)), max_age=3600)  # Store game number
    resp.set_cookie('session_num', str(session_num), max_age=3600)  # Store session number

    return resp

@app.route('/average_message')
def average_message():
    session_num = session.get('session_num', 1)
    participant_id = session['participant_id']  # Retrieve participant ID from session

    # Calculate human averages and divergence
    human_avg_contribution = round(calculate_human_player_average(participant_id), 1)
    historic_human_avg_contribution = 8.1
    human_divergence = round(human_avg_contribution - historic_human_avg_contribution, 1)

    # Calculate AI contributions for the current session
    ai_avg_contribution = round(calculate_ai_player_average(participant_id), 1)
    historic_ai_avg_contribution = 8.1
    ai_divergence = round(ai_avg_contribution - historic_ai_avg_contribution, 1)

    # Log the calculated averages and divergences
    print(f"Human Avg Contribution (Session {session_num}): {human_avg_contribution}")
    print(f"AI Avg Contribution (Session {session_num}): {ai_avg_contribution}")
    print(f"Historic Human Avg Contribution: {historic_human_avg_contribution}")
    print(f"Historic AI Avg Contribution: {historic_ai_avg_contribution}")
    print(f"Human Divergence: {human_divergence}")
    print(f"AI Divergence: {ai_divergence}")

    # Render the template with the calculated data
    resp = make_response(render_template(
        'average_message.html',
        next_session_num=session_num,  # No need to increment again
        human_avg_contribution=human_avg_contribution,
        historic_human_avg_contribution=historic_human_avg_contribution,
        divergence=human_divergence,
        ai_avg_contribution=ai_avg_contribution,
        historic_ai_avg_contribution=historic_ai_avg_contribution,
        ai_divergence=ai_divergence
    ))

    # Set cookies for last visited page, game number, and session number
    resp.set_cookie('last_page', 'average_message', max_age=3600)
    resp.set_cookie('game', str(session.get('game', 1)), max_age=3600)  # Store game number
    resp.set_cookie('session_num', str(session_num), max_age=3600)  # Store session number

    return resp

@app.route('/incom', methods=['GET', 'POST'])
def incom():
    if request.method == 'POST':
        # Retrieve form data
        incom_1 = request.form.get('incom_1')
        incom_2 = request.form.get('incom_2')
        incom_3 = request.form.get('incom_3')
        incom_4 = request.form.get('incom_4')
        incom_5 = request.form.get('incom_5')
        incom_6 = request.form.get('incom_6')

        # Debugging: log incom values to check if they are being retrieved correctly
        print(f"INCOM values: incom_1={incom_1}, incom_2={incom_2}, incom_3={incom_3}, incom_4={incom_4}, incom_5={incom_5}, incom_6={incom_6}")

        # Ensure all questions are answered
        if not all([incom_1, incom_2, incom_3, incom_4, incom_5, incom_6]):
            flash("Please answer all questions before proceeding.")
            return render_template('incom.html')

        # Reverse-code incom_3 (e.g., 5 becomes 1, 4 becomes 2, etc.)
        incom_3_reversed = 6 - int(incom_3)

        # Save the data to the session for now
        session['incom_1'] = incom_1
        session['incom_2'] = incom_2
        session['incom_3'] = incom_3_reversed  # Save reversed
        session['incom_4'] = incom_4
        session['incom_5'] = incom_5
        session['incom_6'] = incom_6

        # Debugging: log session data
        print(f"Session INCOM values: {session.get('incom_1')}, {session.get('incom_2')}, {session.get('incom_3')}, {session.get('incom_4')}, {session.get('incom_5')}, {session.get('incom_6')}")

        # Redirect to the next page
        return redirect(url_for('questions'))  # Redirect to the next step
    return render_template('incom.html')

@app.route('/questions', methods=['GET', 'POST'])
def questions():
    if request.method == 'POST':
        # Check answers from form submission
        answer1 = request.form.get('answer1')
        answer2 = request.form.get('answer2')
        answer3 = request.form.get('answer3')
        answer4 = request.form.get('answer4')

        # Correct answers
        correct_answers = {
            'answer1': ['12.5', '12,5', '12.50', '12,50'],
            'answer2': ['7.5', '7,5', '7.50', '7,50'],
            'answer3': ['10.25', '10,25'],
            'answer4': ['10']
        }

        # Verify answers
        if (answer1 in correct_answers['answer1'] and 
            answer2 in correct_answers['answer2'] and
            answer3 in correct_answers['answer3'] and
            answer4 in correct_answers['answer4']):
            return redirect(url_for('start'))  # Redirect to the first session if answers are correct

    resp = make_response(render_template('questions.html'))

    # Set cookies for last visited page, game number, and session number
    resp.set_cookie('last_page', 'questions', max_age=3600)
    return resp

if __name__ == '__main__':
    app.run(debug=os.getenv("DEBUG", "False") == "True")
