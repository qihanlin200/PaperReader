"""Paper-scoped conversations with backwards-compatible message migration."""
from datetime import datetime
import uuid


def create_session():
    return {'id': uuid.uuid4().hex, 'title': '新会话',
            'created_at': datetime.now().astimezone().isoformat(timespec='seconds'), 'messages': []}


def ensure_sessions(paper):
    if not paper.get('sessions'):
        session = create_session()
        session['messages'] = paper.get('messages', [])
        if session['messages']:
            session['title'] = session['messages'][0].get('question', session['messages'][0]['content'])[-80:]
        paper['sessions'] = [session]; paper['active_session'] = session['id']
    for session in paper["sessions"]:
        session.pop("noted_answers", None)
    current = next((s for s in paper['sessions'] if s['id'] == paper.get('active_session')), paper['sessions'][0])
    paper['active_session'] = current['id']
    paper['messages'] = current['messages']
    return current
