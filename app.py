import os
from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
import numpy as np
import secrets
import time


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', '4I6YU5ERTUC4')

# Database setup
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///public_good_game.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Game settings
initial_tokens = 20
max_contribution = 10
typical_contribution = 8  # Fixed value for comparison
total_rounds = 10
total_sessions = 2  # Number of sessions set to 2

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

    __table_args__ = (db.UniqueConstraint('participant_id', 'session_num', 'round_num', name='_participant_session_round_uc'),)

    def __repr__(self):
        return f'<Participant {self.participant_id} - Session {self.session_num}, Round {self.round_num}>'

# Create the database
with app.app_context():
    db.create_all()

@app.route('/')
def welcome():
    # Assign a random participant ID if it does not exist
    if 'participant_id' not in session:
        session['participant_id'] = secrets.token_hex(8)
    return render_template('welcome.html')

@app.route('/instructions')
def instructions():
    session['instructions_completed'] = True
    return render_template('instructions.html')

@app.route('/start')
def start():
    # Randomly assign to control or experimental group
    if 'group' not in session:
        session['group'] = np.random.choice(['control', 'experimental'])

    # Initialize session data only if it does not exist
    if 'session_num' not in session:
        session['session_num'] = 1

    session['round'] = 1
    session['contributions'] = []
    session['bot_contributions'] = []
    session['participant_balances'] = [initial_tokens]
    session['bot_balances'] = [initial_tokens]
    session['participant_balance'] = initial_tokens
    session['bot_balance'] = initial_tokens
    session['intervention'] = False
    session['session_started'] = True
    session['start_time'] = time.time()  # Record the start time of the first round

    return redirect(url_for('game'))

@app.route('/game')
def game():
    session['start_time'] = time.time()  # Record the start time of the current round
    round_num = session['round']
    session_num = session['session_num']
    balance = session.get('participant_balance', initial_tokens)  # Ensure balance is initialized
    round_balance = session.get('round_balance', None)
    return render_template('index.html', session_num=session_num, round=round_num, balance=balance, round_balance=round_balance)

@app.route('/play/<int:contribution>', methods=['POST'])
def play(contribution):
    # Calculate the elapsed time since the round started
    elapsed_time = time.time() - session['start_time']
    time_exceeded = 1 if elapsed_time > 8 else 0  # Check if time exceeded 8 seconds

    # Bot mimics participant's previous contributions with noise
    if session['round'] == 1 and not session['bot_contributions']:
        bot_contribution = np.random.randint(0, max_contribution + 1)
    else:
        prev_participant_contrib = session['contributions'][-1] if session['contributions'] else np.random.randint(0, max_contribution + 1)
        noise = np.random.randint(-2, 3)  # Add noise in the range [-2, 2]
        bot_contribution = prev_participant_contrib + noise
        bot_contribution = max(0, min(bot_contribution, max_contribution))  # Ensure within bounds

    round_num = session['round']
    session_num = session['session_num']
    participant_balance = session['participant_balance']
    bot_balance = session['bot_balance']

    # Record contributions
    contributions = session['contributions']
    bot_contributions = session['bot_contributions']
    participant_balances = session['participant_balances']
    bot_balances = session['bot_balances']
    
    contributions.append(contribution)
    bot_contributions.append(bot_contribution)

    # Calculate new balances
    total_contribution = contribution + bot_contribution
    if total_contribution > 10:
        total_contribution *= 1.3
    total_contribution = int(total_contribution)
    round_balance = total_contribution // 2

    net_gain = round_balance - contribution
    participant_balance += net_gain
    bot_balance += round_balance - bot_contribution

    # Save updated balances in the session
    session['participant_balance'] = round(participant_balance)
    session['bot_balance'] = round(bot_balance)
    session['round_balance'] = round(round_balance)
    participant_balances.append(round(participant_balance))
    bot_balances.append(round(bot_balance))
    session['participant_balances'] = participant_balances
    session['bot_balances'] = bot_balances
    session['net_gain'] = net_gain

    # Save data to the database
    participant_entry = Participant(
        participant_id=session['participant_id'],
        group=session['group'],
        session_num=session_num,
        round_num=round_num,
        contribution=contribution,
        bot_contribution=bot_contribution,
        participant_balance=participant_balance,
        bot_balance=bot_balance,
        net_gain=net_gain,
        time_exceeded=time_exceeded
    )
    db.session.add(participant_entry)
    db.session.commit()

    # Check if game should end
    if participant_balance <= 0 or bot_balance <= 0:
        return redirect(url_for('result'))

    # Prepare for next round
    round_num += 1
    session['round'] = round_num
    if round_num > total_rounds:
        if session_num == 1 and not session.get('intervention', False):
            session['intervention'] = True
            if session['group'] == 'control':
                return redirect(url_for('message'))
            else:
                return redirect(url_for('average_message'))
        else:
            return redirect(url_for('result'))
    session['start_time'] = time.time()  # Reset start time for the next round
    return redirect(url_for('waiting'))

@app.route('/waiting')
def waiting():
    wait_time = round(np.random.uniform(2.5, 4.5), 1)
    session['wait_time'] = wait_time
    return render_template('waiting.html', wait_time=wait_time)

@app.route('/outcome')
def outcome():
    net_gain = session.get('net_gain', 0)  # Ensure net_gain is initialized
    participant_balance = session.get('participant_balance', initial_tokens)  # Ensure balance is initialized
    return render_template('outcome.html', net_gain=net_gain, total_balance=participant_balance)

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
    average_contribution = round(sum(contributions) / len(contributions))
    divergence = average_contribution - typical_contribution
    if divergence > 0:
        message = f"You have contributed on average <span class='highlight'>{divergence}</span> more than the previous participants."
    elif divergence < 0:
        message = f"You have contributed on average <span class='highlight'>{-divergence}</span> less than the previous participants."
    else:
        message = f"You have contributed on average <span class='highlight'>{average_contribution}</span>. Exactly the same as others typically contribute in this game."
    additional_message = "Another player has also received information regarding their deviation from the average contribution."
    return render_template('average_message.html', message=message, additional_message=additional_message, next_session_num=next_session_num)

@app.route('/continue_game')
def continue_game():
    # Increment session number
    session['session_num'] += 1
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
    session_1_participant_balance = db.session.query(Participant.participant_balance).filter_by(participant_id=session['participant_id'], session_num=1).order_by(Participant.round_num.desc()).first()[0]
    session_1_bot_balance = db.session.query(Participant.bot_balance).filter_by(participant_id=session['participant_id'], session_num=1).order_by(Participant.round_num.desc()).first()[0]
    session_2_participant_balance = db.session.query(Participant.participant_balance).filter_by(participant_id=session['participant_id'], session_num=2).order_by(Participant.round_num.desc()).first()[0]
    session_2_bot_balance = db.session.query(Participant.bot_balance).filter_by(participant_id=session['participant_id'], session_num=2).order_by(Participant.round_num.desc()).first()[0]

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
