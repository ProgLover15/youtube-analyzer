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

if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY must be set in environment variables")

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly"
]

CLIENT_SECRETS_FILE = {
    "web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": [os.getenv("REDIRECT_URI", "http://127.0.0.1:5000/auth/callback")] 
    }
}

def build_youtube_service():
    if 'credentials' not in session:
        return None
    from google.oauth2.credentials import Credentials
    credentials = Credentials(**session['credentials'])
    return googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# --- 認証ルート ---
@app.route('/auth/google')
def auth_google():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = url_for('auth_callback', _external=True)
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent' # 審査を通しやすくするために追加
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/auth/callback')
def auth_callback():
    state = session.get('state')
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    flow.redirect_uri = url_for('auth_callback', _external=True)

    authorization_response = request.url
    if authorization_response.startswith('http:'):
        authorization_response = authorization_response.replace('http:', 'https:', 1)

    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    return redirect(url_for('index'))

@app.route('/auth/logout') # index.htmlの呼び出しに合わせました
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/auth/status')
def auth_status():
    if 'credentials' in session:
        return jsonify({"status": "authenticated"})
    return jsonify({"error": "Not authenticated"}), 401

# --- APIエンドポイント (ここも全部含めました) ---
@app.route('/api/all-channels')
def get_all_channels():
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
    all_subscriptions = []
    next_page_token = None
    try:
        while True:
            req = youtube.subscriptions().list(
                part="snippet",
                mine=True,
                maxResults=50,
                pageToken=next_page_token
            )
            response = req.execute()
            for item in response.get("items", []):
                all_subscriptions.append({
                    "subscriptionId": item["id"],
                    "channelId": item["snippet"]["resourceId"]["channelId"],
                    "title": item["snippet"]["title"],
                    "thumbnails": item["snippet"]["thumbnails"]["default"]["url"],
                    "lastUploadDate": "pending",
                    "isSubscribed": True,
                })
            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break
        return jsonify(all_subscriptions)
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze_channel():
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json()
    channel_id = data.get('channelId')
    try:
        channel_response = youtube.channels().list(
            part="contentDetails", id=channel_id
        ).execute()
        if not channel_response.get("items"):
            return jsonify({"channelId": channel_id, "lastUploadDate": None})
        
        uploads_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        playlist_response = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=1
        ).execute()
        
        last_date = None
        if playlist_response.get("items"):
            last_date = playlist_response["items"][0]["snippet"]["publishedAt"]
        return jsonify({"channelId": channel_id, "lastUploadDate": last_date})
    except:
        return jsonify({"channelId": channel_id, "lastUploadDate": None})

@app.route('/api/subscriptions/bulk-delete', methods=['POST'])
def bulk_delete_subscriptions():
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json()
    ids = data.get('subscriptionIds', [])
    success, fail = 0, 0
    for sub_id in ids:
        try:
            youtube.subscriptions().delete(id=sub_id).execute()
            success += 1
        except:
            fail += 1
    return jsonify({"successCount": success, "failCount": fail})

if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app.run(debug=True, port=5000)
