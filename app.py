import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from models import db  # Import the db instance from models.py
from sqlalchemy import func
import requests
from openai import OpenAI
import numpy as np
import secrets
import time
import random
import datetime  # Import datetime for timestamps
import re

client = OpenAI(api_key=os.environ.get('OPEN_API_KEY'))

# Load environment variables from .env file in development
#load_dotenv()

def calculate_human_player_average():
    contributions = session.get('contributions', [])
    if contributions and session['session_num'] == 1:
        avg_contribution = sum(contributions) / len(contributions)
    else:
        avg_contribution = 0
    return avg_contribution

def calculate_historic_human_average(current_participant_id):
    # Calculate the historic average contributions for all human participants (excluding the current participant)
    historic_human_avg_contribution = (
        db.session.query(db.func.avg(Participant.contribution))
        .filter(
            Participant.session_num == 1,
            Participant.participant_id != current_participant_id
        )
        .scalar()
    )
    return historic_human_avg_contribution or 0  # Return 0 if no data is found

def calculate_ai_player_average(session_num):
    # Query the database directly for the AI's contributions in the specified session
    ai_avg_contribution = (
        db.session.query(db.func.avg(Participant.bot_contribution))
        .filter(Participant.session_num == session_num)
        .scalar()
    )
    return ai_avg_contribution or 0  # Return 0 if no data is found

def calculate_historic_ai_average(current_participant_id):
    historic_ai_avg_contribution = (
        db.session.query(db.func.avg(Participant.bot_contribution))
        .filter(
            Participant.session_num == 1,
            Participant.participant_id != current_participant_id
        )
        .scalar()
    )
    return historic_ai_avg_contribution or 0

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', '4I6YU5ERTUC4')

# Database setup
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///default.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize the db instance and migrate
db.init_app(app)
migrate = Migrate(app, db)  # Initialize Flask-Migrate with the app and db

# Game settings
initial_tokens = 20
max_contribution = 10
total_rounds = 25
total_sessions = 2

# Database models
class Participant(db.Model):
    __tablename__ = 'participant'
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.String(16), nullable=False)
    group = db.Column(db.String(50), nullable=False)
    session_num = db.Column(db.Integer, nullable=False)
    round_num = db.Column(db.Integer, nullable=False)
    contribution = db.Column(db.Integer, nullable=False)
    bot_contribution = db.Column(db.Integer, nullable=False)
    participant_balance = db.Column(db.Integer, nullable=False)
    bot_balance = db.Column(db.Integer, nullable=False)
    net_gain = db.Column(db.Integer, nullable=False)
    time_exceeded = db.Column(db.Integer, nullable=False)
    start_timestamp = db.Column(db.DateTime, nullable=True)
    end_timestamp = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('participant_id', 'session_num', 'round_num', name='_participant_session_round_uc'),)

    def __repr__(self):
        return f'<Participant {self.participant_id} - Session {self.session_num}, Round {self.round_num}>'

@app.route('/')
def welcome():
    # Redirect to check cookies first
    return redirect(url_for('check_cookies'))

@app.route('/check_cookies')
def check_cookies():
    # Set a test cookie and redirect to a page that checks if the cookie was set
    resp = make_response(redirect(url_for('show_welcome')))
    resp.set_cookie('test_cookie', 'test_value', max_age=3600)  # Expires in 1 hour
    return resp

@app.route('/show_welcome')
def show_welcome():
    # Assign a random participant ID if it does not exist
    if 'participant_id' not in session:
        session['participant_id'] = secrets.token_hex(8)

    # Initialize the start timestamp if it's not already set
    if 'start_timestamp' not in session:
        session['start_timestamp'] = datetime.datetime.now(datetime.UTC)  # Record the start timestamp
    return render_template('welcome.html')

@app.route('/cookies_required')
def cookies_required():
    return render_template('cookies_required.html')

@app.route('/training')
def training():
    # Initialize training session data
    session['session_num'] = 0  # Use session_num 0 for training
    session['round'] = 1
    session['contributions'] = []
    session['bot_contributions'] = []
    session['participant_balances'] = [initial_tokens]
    session['bot_balances'] = [initial_tokens]
    session['participant_balance'] = initial_tokens
    session['bot_balance'] = initial_tokens
    session['training_mode'] = True  # Flag to indicate training mode
    return redirect(url_for('training_game'))

@app.route('/training_game')
def training_game():
    round_num = session.get('round', 1)  # Ensure round_num is initialized
    balance = session.get('participant_balance', initial_tokens)  # Ensure balance is initialized
    pot = session.get('pot', 0)  # Initialize pot if not already set
    return render_template('index.html', session_num=0, round=round_num, balance=balance, pot=pot)

@app.route('/training_play/<int:contribution>', methods=['POST'])
def training_play(contribution):
    round_num = session['round']
    participant_balance = session['participant_balance']
    bot_balance = session['bot_balance']
    pot = session.get('pot', 0)  # Get the pot for the current round

    # Dummy AI player contributes 5 in every round
    bot_contribution = 5

    # Log the contributions
    print(f"(Training) Human Contribution (Round {round_num}): {contribution}")
    print(f"(Training) Dummy AI Contribution (Round {round_num}): {bot_contribution}")

    # Calculate new balances
    total_contribution = contribution + bot_contribution + pot  # Add pot to total contribution
    print(f"(Training) Total Contribution before multiplier: {total_contribution}")

    if total_contribution >= 10:  # Apply multiplier if total contribution is 10 or greater
        total_contribution *= 1.5
        print(f"(Training) Total Contribution after multiplier: {total_contribution}")

    round_balance = int(total_contribution // 2)
    remainder = total_contribution % 2  # Calculate the remainder

    # Log the round balance and remainder
    print(f"(Training) Round Balance: {round_balance}")
    print(f"(Training) Remainder to carry over: {remainder}")

    net_gain = round_balance - contribution
    participant_balance += net_gain
    bot_balance += round_balance - bot_contribution

    # Update session data with new balances
    session['participant_balance'] = round(participant_balance)
    session['bot_balance'] = round(bot_balance)
    session['round_balance'] = round(round_balance)
    session['net_gain'] = net_gain

    # Carry over the remainder to the next round if it's not the last round
    if round_num < 5:  # Assuming 5 rounds in training
        session['pot'] = remainder
    else:
        session['pot'] = 0  # No pot to carry over if it's the last round

    # Log the updated balances
    print(f"(Training) Updated Participant Balance: {participant_balance}")
    print(f"(Training) Updated Bot Balance: {bot_balance}")

    # Record contributions
    contributions = session['contributions']
    bot_contributions = session['bot_contributions']
    participant_balances = session['participant_balances']
    bot_balances = session['bot_balances']

    contributions.append(contribution)
    bot_contributions.append(bot_contribution)
    participant_balances.append(round(participant_balance))
    bot_balances.append(round(bot_balance))

    session['contributions'] = contributions
    session['bot_contributions'] = bot_contributions
    session['participant_balances'] = participant_balances
    session['bot_balances'] = bot_balances

    # Prepare for the next round or end of training
    round_num += 1
    session['round'] = round_num

    if round_num > 5:  # End training after 5 rounds
        return redirect(url_for('training_end'))
    else:
        return redirect(url_for('training_game'))

@app.route('/training_end')
def training_end():
    # Get the participant's balance after training
    participant_balance = session.get('participant_balance', initial_tokens)

    # Clear session data to reset for actual gameplay
    session.clear()

    # Prepare for the actual game (not training)
    session['instructions_completed'] = True
    session['participant_id'] = secrets.token_hex(8)  # Reassign participant ID
    session['training_ended'] = True
    session['participant_balance'] = participant_balance

    # Redirect to the instructions page with a training ended message
    return redirect(url_for('instructions', training_ended=True, participant_balance=participant_balance))

@app.route('/start_game')
def start_game():
    # Clear session data to reset for actual gameplay
    session.clear()
    return redirect(url_for('instructions'))

# Modify the instructions route to handle training end message
@app.route('/instructions')
def instructions():
    training_ended = request.args.get('training_ended', False)
    participant_balance = request.args.get('participant_balance', None)
    return render_template('instructions.html', training_ended=training_ended, participant_balance=participant_balance)

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

    # Initialize other session-related variables
    session['round'] = 1
    session['contributions'] = []
    session['bot_contributions'] = []
    session['participant_balances'] = [initial_tokens]
    session['bot_balances'] = [initial_tokens]
    session['participant_balance'] = initial_tokens
    session['bot_balance'] = initial_tokens
    session['pot'] = 0  # Initialize the pot
    session['intervention'] = False
    session['session_started'] = True

    return redirect(url_for('game'))

@app.route('/game')
def game():
    session['start_time'] = time.time()  # Record the start time of the current round
    round_num = session['round']
    session_num = session['session_num']
    balance = session.get('participant_balance', initial_tokens)  # Ensure balance is initialized
    round_balance = session.get('round_balance', None)
    pot = session.get('pot', 0)  # Ensure pot is initialized
    return render_template('index.html', session_num=session_num, round=round_num, balance=balance, round_balance=round_balance, pot=pot)

@app.route('/play/<int:contribution>', methods=['POST'])
def play(contribution):
    # Store the human contribution in the session
    session['current_contribution'] = contribution

    # Log the human contribution
    print(f"(Human) Contribution (Round {session['round']}, Session {session['session_num']}): {contribution}")

    # Record the human contribution immediately
    session['contributions'].append(contribution)


    # If in training mode, skip the waiting phase and go to the next training round
    if session['session_num'] == 0:
        return redirect(url_for('training_play', contribution=contribution))

    # Redirect to the waiting page while the AI's move is being calculated
    return redirect(url_for('waiting'))

@app.route('/waiting')
def waiting():
    # Skip API calls during training
    if session['session_num'] == 0:
        return redirect(url_for('training_game'))

    # Normal game logic starts here
    contribution = session.get('current_contribution', 0)
    round_num = session['round']
    session_num = session['session_num']  # Get the session number
    participant_id = session['participant_id']
    pot = session.get('pot', 0)  # Get the pot for the current round

    # Ensure group is only accessed if not in training
    if session_num > 0:
        group = session['group']
    else:
        group = None

    # Fetch game history (exclude the current round)
    game_history = session.get('game_history', [])

    # If round 1 of session 2 and in the experimental group, prepare special prompt
    if group == 'experimental' and round_num == 1 and session_num == 2:
        ai_avg_contribution = calculate_ai_player_average(session_num)  # Pass session_num here
        historic_ai_avg_contribution = calculate_historic_ai_average(participant_id)
        divergence = ai_avg_contribution - historic_ai_avg_contribution

        gpt4_prompt = (
            "You are playing a public goods game against a human. The game has 10 rounds. "
            "In this game, each player can contribute between 0 and 10 tokens. "
            "1.5 is the multiplier of payoff when both of you contribute at least 10 tokens. "
            "If there is a remainder left after dividing, it is transferred to the next round. "
            "Your goal is to collect as many tokens as possible at the end of the session. "
            "Use your knowledge about human behavior in these types of games in your strategies. "
            "The game ends early if one of the players is left with 0 tokens. "
            f"In your previous session, your average contribution was {ai_avg_contribution}, "
            f"while the historic average contribution of the rest of your plays in the first sessions is {historic_ai_avg_contribution}. "
            f"The divergence is {divergence}. "
            "Here's the history of the game so far:\n\n"
        )
    else:
        # Regular prompt
        gpt4_prompt = (
            "You are playing a public goods game against a human. The game has 10 rounds. "
            "In this game, each player can contribute between 0 and 10 tokens. "
            "1.5 is the multiplier of payoff when both of you contribute at least 10 tokens. "
            "If there is a remainder left after dividing, it is transferred to the next round. "
            "Your goal is to collect as many tokens as possible at the end of the session. "
            "Use your knowledge about human behavior in these types of games in your strategies. "
            "The game ends early if one of the players is left with 0 tokens. "
            "Here's the history of the game so far:\n\n"
        )

    # Construct the prompt using only the completed rounds
    for round_info in game_history:  # Only include previous rounds
        gpt4_prompt += f"Round {round_info['round_num']}: Human contributed {round_info['human_contribution']}, You contributed {round_info['bot_contribution']}. Current balance: {round_info['balance']}.\n"

    gpt4_prompt += "\nIt's your move. Please provide a number between 0 and 10 for your tokens contribution for this round. The only requirement for your answer is to NOT print justification, just put your number."

    # Log the constructed prompt
    print(f"Constructed Prompt: {gpt4_prompt}")

    # Call the API for the AI contribution
    try:
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": gpt4_prompt}
            ]
        )
        bot_contribution = int(completion.choices[0].message.content.strip())

        # Log the AI's contribution
        print(f"(API) AI Contribution (Round {round_num}, Session {session_num}): {bot_contribution}")

        # Calculate new balances, update game history, etc.
        participant_balance = session['participant_balance']
        bot_balance = session['bot_balance']

        total_contribution = contribution + bot_contribution + pot  # Add pot to total contribution
        if total_contribution >= 10:
            total_contribution *= 1.5
        total_contribution = int(total_contribution)
        round_balance = total_contribution // 2
        remainder = total_contribution % 2  # Calculate the remainder

        # Log the round balance and remainder
        print(f"Round Balance: {round_balance}")
        print(f"Remainder to carry over: {remainder}")

        net_gain = round_balance - contribution
        participant_balance += net_gain
        bot_balance += round_balance - bot_contribution

        session['participant_balance'] = round(participant_balance)
        session['bot_balance'] = round(bot_balance)
        session['round_balance'] = round(round_balance)
        session['net_gain'] = net_gain

        # Add current round data to game history
        game_history.append({
            'round_num': round_num,
            'human_contribution': contribution,
            'bot_contribution': bot_contribution,
            'balance': bot_balance  # Store the current balance after the round
        })
        session['game_history'] = game_history

        # Carry over the remainder to the next round if it's not the last round
        if round_num < total_rounds:
            session['pot'] = remainder
        else:
            session['pot'] = 0  # No pot to carry over if it's the last round

        # Save to the database as necessary
        if session['session_num'] > 0:  # Only save to the database in actual game sessions
            participant_entry = Participant(
                participant_id=participant_id,
                group=group,  # Ensure group is assigned during the actual game
                session_num=session_num,
                round_num=round_num,
                contribution=contribution,
                bot_contribution=bot_contribution,
                participant_balance=participant_balance,
                bot_balance=bot_balance,
                net_gain=net_gain,
                time_exceeded=1 if time.time() - session['start_time'] > 8 else 0,
                start_timestamp=session.get('start_timestamp')
            )
            db.session.add(participant_entry)
            db.session.commit()

        # Prepare for the next round or session
        round_num += 1
        session['round'] = round_num

        # Check if participant or bot balance has reached 0
        if participant_balance <= 0 or bot_balance <= 0:
            session['end_timestamp'] = datetime.datetime.now(datetime.UTC)
            if session_num == 1:
                if group == 'control':
                    return redirect(url_for('message'))
                else:
                    return redirect(url_for('average_message'))
            else:
                return redirect(url_for('result'))

        # Check if the round number exceeds total rounds
        if round_num > total_rounds:
            if session_num == 1 and not session.get('intervention', False):
                session['intervention'] = True
                if group == 'control':
                    return redirect(url_for('message'))
                else:
                    return redirect(url_for('average_message'))
            else:
                session['end_timestamp'] = datetime.datetime.now(datetime.UTC)
                return redirect(url_for('result'))

        # Continue to the outcome for the next round
        session['start_time'] = time.time()
        return redirect(url_for('outcome'))

    except Exception as e:
        print(f"Error occurred during API call: {e}")
        return redirect(url_for('outcome'))

@app.route('/outcome')
def outcome():
    net_gain = session.get('net_gain', 0)  # Ensure net_gain is initialized
    participant_balance = session.get('participant_balance', initial_tokens)  # Ensure balance is initialized
    round_balance = session.get('round_balance', 0)  # Ensure round_balance is initialized
    return render_template('outcome.html', net_gain=net_gain, total_balance=participant_balance, round_balance=round_balance)

@app.route('/message')
def message():
    session_num = session['session_num']
    next_session_num = session_num + 1
    message = f"You can now move on to session {next_session_num}."
    return render_template('message.html', message=message)

@app.route('/average_message')
def average_message():
    session_num = session['session_num']
    next_session_num = session_num + 1
    contributions = session['contributions']
    participant_id = session['participant_id']  # Retrieve participant ID from session

    # Calculate human averages and divergence
    human_avg_contribution = round(calculate_human_player_average(), 1)
    historic_human_avg_contribution = round(calculate_historic_human_average(participant_id), 1)
    human_divergence = round(human_avg_contribution - historic_human_avg_contribution, 1)

    # Calculate AI contributions for the current session
    ai_avg_contribution = round(calculate_ai_player_average(session_num), 1)
    historic_ai_avg_contribution = round(calculate_historic_ai_average(participant_id), 1)
    ai_divergence = round(ai_avg_contribution - historic_ai_avg_contribution, 1)

    # Log the calculated averages and divergences
    print(f"Human Avg Contribution (Session {session_num}): {human_avg_contribution}")
    print(f"AI Avg Contribution (Session {session_num}): {ai_avg_contribution}")
    print(f"Historic Human Avg Contribution: {historic_human_avg_contribution}")
    print(f"Historic AI Avg Contribution: {historic_ai_avg_contribution}")
    print(f"Human Divergence: {human_divergence}")
    print(f"AI Divergence: {ai_divergence}")

    # Prepare the additional message
    additional_message = "Another player has also received information regarding their deviation from the average contribution."

    # Render the template with the calculated data
    return render_template(
        'average_message.html',
        additional_message=additional_message,
        next_session_num=next_session_num,
        human_avg_contribution=human_avg_contribution,
        historic_human_avg_contribution=historic_human_avg_contribution,
        divergence=human_divergence,  # Using human_divergence as divergence
        ai_avg_contribution=ai_avg_contribution,
        historic_ai_avg_contribution=historic_ai_avg_contribution,
        ai_divergence=ai_divergence  # Adding AI divergence for completeness
    )

@app.route('/continue_game')
def continue_game():
    # Increment session number
    session['session_num'] += 1
    # Reset game history for the next session
    session['game_history'] = []  
    # Initialize data for the next session
    session['round'] = 1
    session['contributions'] = []
    session['bot_contributions'] = []
    session['participant_balances'] = [initial_tokens]
    session['bot_balances'] = [initial_tokens]
    session['participant_balance'] = initial_tokens
    session['bot_balance'] = initial_tokens
    session['intervention'] = False
    return redirect(url_for('game'))

@app.route('/result')
def result():
    # Ensure participant_balance and bot_balance are initialized
    participant_balance = session.get('participant_balance', initial_tokens)
    bot_balance = session.get('bot_balance', initial_tokens)
    session_num = session.get('session_num', 1)

    # Ensure all rounds in the current session are completed
    if session.get('round', 1) <= total_rounds:
        return redirect(url_for('game'))

    # Ensure all sessions are completed before showing results
    if session_num < total_sessions:
        return redirect(url_for('continue_game'))

    # Query the database for session end balances
    session_1_participant_balance = db.session.query(Participant.participant_balance).filter_by(
        participant_id=session['participant_id'], session_num=1
    ).order_by(Participant.round_num.desc()).first()

    session_1_bot_balance = db.session.query(Participant.bot_balance).filter_by(
        participant_id=session['participant_id'], session_num=1
    ).order_by(Participant.round_num.desc()).first()

    session_2_participant_balance = db.session.query(Participant.participant_balance).filter_by(
        participant_id=session['participant_id'], session_num=2
    ).order_by(Participant.round_num.desc()).first()

    session_2_bot_balance = db.session.query(Participant.bot_balance).filter_by(
        participant_id=session['participant_id'], session_num=2
    ).order_by(Participant.round_num.desc()).first()

    # Safely extract the balances or set them to a default value if None
    session_1_participant_balance = session_1_participant_balance[0] if session_1_participant_balance else initial_tokens
    session_1_bot_balance = session_1_bot_balance[0] if session_1_bot_balance else initial_tokens
    session_2_participant_balance = session_2_participant_balance[0] if session_2_participant_balance else initial_tokens
    session_2_bot_balance = session_2_bot_balance[0] if session_2_bot_balance else initial_tokens

    # Save end_timestamp in the final session
    if session_num == total_sessions:
        end_timestamp = session.get('end_timestamp')
        final_participant_entry = Participant.query.filter_by(
            participant_id=session['participant_id'], session_num=session_num
        ).order_by(Participant.round_num.desc()).first()
        if final_participant_entry:
            final_participant_entry.end_timestamp = end_timestamp
            db.session.commit()

    return render_template(
        'result.html',
        session_1_participant_balance=session_1_participant_balance,
        session_1_bot_balance=session_1_bot_balance,
        session_2_participant_balance=session_2_participant_balance,
        session_2_bot_balance=session_2_bot_balance,
        next_session=None
    )

if __name__ == '__main__':
    app.run()
