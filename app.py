import os
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from flask import Flask, redirect, request, session, url_for, jsonify, send_from_directory
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv("FLASK_SECRET_KEY")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
SCOPES = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.readonly"]

CLIENT_SECRETS_FILE = {
    "web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": ["http://127.0.0.1:5000/auth/callback"] 
    }
}

def build_youtube_service():
    if 'credentials' not in session: return None
    from google.oauth2.credentials import Credentials
    return googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=Credentials(**session['credentials']))

@app.route('/')
def index(): return send_from_directory('.', 'index.html')

@app.route('/auth/google')
def auth_google():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = url_for('auth_callback', _external=True)
    auth_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['state'] = state
    return redirect(auth_url)

@app.route('/auth/callback')
def auth_callback():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(CLIENT_SECRETS_FILE, scopes=SCOPES, state=session['state'])
    flow.redirect_uri = url_for('auth_callback', _external=True)
    auth_resp = request.url.replace('http:', 'https:', 1) if request.url.startswith('http:') else request.url
    flow.fetch_token(authorization_response=auth_resp)
    creds = flow.credentials
    session['credentials'] = {
        'token': creds.token, 'refresh_token': creds.refresh_token, 
        'token_uri': creds.token_uri, 'client_id': creds.client_id, 
        'client_secret': creds.client_secret, 'scopes': creds.scopes
    }
    return redirect(url_for('index'))

@app.route('/auth/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/auth/status')
def auth_status():
    return jsonify({"status": "authenticated" if 'credentials' in session else "unauthenticated"})

@app.route('/api/all-channels')
def get_all_channels():
    youtube = build_youtube_service()
    if not youtube: return jsonify({"error": "Unauthorized"}), 401
    subs = []
    token = None
    try:
        while True:
            res = youtube.subscriptions().list(part="snippet", mine=True, maxResults=50, pageToken=token).execute()
            for item in res.get("items", []):
                subs.append({
                    "subscriptionId": item["id"],
                    "channelId": item["snippet"]["resourceId"]["channelId"],
                    "channelName": item["snippet"]["title"],
                    "thumbnailUrl": item["snippet"]["thumbnails"]["default"]["url"],
                    "lastUploadDate": "pending",
                    "isSubscribed": True
                })
            token = res.get("nextPageToken")
            if not token: break
        return jsonify(subs)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze_channel():
    youtube = build_youtube_service()
    data = request.get_json()
    ch_id = data.get('channelId')
    try:
        res = youtube.channels().list(part="contentDetails", id=ch_id).execute()
        up_id = res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        items = youtube.playlistItems().list(part="snippet", playlistId=up_id, maxResults=1).execute()
        date = items["items"][0]["snippet"]["publishedAt"] if items.get("items") else None
        return jsonify({"channelId": ch_id, "lastUploadDate": date})
    except: return jsonify({"channelId": ch_id, "lastUploadDate": None})

@app.route('/api/subscriptions/bulk-delete', methods=['POST'])
def bulk_delete():
    youtube = build_youtube_service()
    ids = request.get_json().get('subscriptionIds', [])
    success = 0
    for sid in ids:
        try:
            youtube.subscriptions().delete(id=sid).execute()
            success += 1
        except: pass
    return jsonify({"successCount": success})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
