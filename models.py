from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

db = SQLAlchemy()

class Participant(db.Model):
    __tablename__ = 'participant'
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.String(16), nullable=False)
    prolific_pid = db.Column(db.String(64), nullable=False)  # Prolific participant ID
    session_id = db.Column(db.String(64), nullable=False)  # Prolific session ID
    group = db.Column(db.String(50), nullable=False)
    session_num = db.Column(db.Integer, nullable=False)
    round_num = db.Column(db.Integer, nullable=False)
    contribution = db.Column(db.Integer, nullable=False)
    bot_contribution = db.Column(db.Integer, nullable=False)
    participant_balance = db.Column(db.Float, nullable=False)
    bot_balance = db.Column(db.Float, nullable=False)
    net_gain = db.Column(db.Float, nullable=False)
    start_timestamp = db.Column(db.DateTime, nullable=True)
    end_timestamp = db.Column(db.DateTime, nullable=True)
    bonus = db.Column(db.Float, nullable=True)
    incom_1 = db.Column(db.Integer, nullable=True)
    incom_2 = db.Column(db.Integer, nullable=True)
    incom_3 = db.Column(db.Integer, nullable=True)
    incom_4 = db.Column(db.Integer, nullable=True)
    incom_5 = db.Column(db.Integer, nullable=True)
    incom_6 = db.Column(db.Integer, nullable=True)

    __table_args__ = (db.UniqueConstraint('participant_id', 'session_num', 'round_num', name='_participant_session_round_uc'),)

    def __repr__(self):
        return f'<Participant {self.participant_id} - Session {self.session_num}, Round {self.round_num}>'

def save_participant_data(prolific_pid, session_id, participant_id, session_num, round_num, contribution, bot_contribution, participant_balance, bot_balance, net_gain, group, start_timestamp, end_timestamp, incom_1, incom_2, incom_3, incom_4, incom_5, incom_6):
    try:
        # Check if the record already exists
        existing_entry = Participant.query.filter_by(
            participant_id=participant_id,
            session_num=session_num,
            round_num=round_num
        ).first()

        if not existing_entry:
            # If no record exists, insert a new entry
            participant_entry = Participant(
                prolific_pid=prolific_pid,
                session_id=session_id,
                participant_id=participant_id,
                group=group,
                session_num=session_num,
                round_num=round_num,
                contribution=contribution,
                bot_contribution=bot_contribution,
                participant_balance=participant_balance,
                bot_balance=bot_balance,
                net_gain=net_gain,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                incom_1=incom_1, 
                incom_2=incom_2, 
                incom_3=incom_3, 
                incom_4=incom_4, 
                incom_5=incom_5, 
                incom_6=incom_6
            )
            db.session.add(participant_entry)
            db.session.commit()  # Commit the session
        else:
            print(f"Record already exists for participant_id={participant_id}, session_num={session_num}, round_num={round_num}")

    except IntegrityError as e:
        db.session.rollback()
        print(f"Error occurred: {e}")
    except Exception as e:
        db.session.rollback()
        print(f"Unexpected error: {e}")

# Calculate averages for the human and AI player contributions
def calculate_human_player_average(participant_id):
    # Calculate the average human contribution for the given participant
    result = db.session.query(func.avg(Participant.contribution)).filter_by(participant_id=participant_id).first()
    return result[0] if result[0] is not None else 0.0  # Return 0.0 if no results found

def calculate_ai_player_average(participant_id):
    # Calculate the average AI contribution for the given participant
    result = db.session.query(func.avg(Participant.bot_contribution)).filter_by(participant_id=participant_id).first()
    return result[0] if result[0] is not None else 0.0  # Return 0.0 if no results found
