import os
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from flask import Flask, redirect, request, session, url_for, jsonify, send_from_directory
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# .envファイルから環境変数を読み込む
load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# 本番環境(HTTPS)対応
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
        "redirect_uris": ["http://127.0.0.1:5000/auth/callback"] 
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

@app.route('/auth/google')
def auth_google():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = url_for('auth_callback', _external=True)
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
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

@app.route('/auth/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/auth/status')
def auth_status():
    if 'credentials' in session:
        return jsonify({"status": "authenticated"})
    return jsonify({"status": "unauthenticated"}), 200

@app.route('/api/all-channels')
def get_all_channels():
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
    all_subscriptions = []
    next_page_token = None
    try:
        while True:
            res = youtube.subscriptions().list(
                part="snippet", mine=True, maxResults=50, pageToken=next_page_token
            ).execute()
            for item in res.get("items", []):
                all_subscriptions.append({
                    "subscriptionId": item["id"],
                    "channelId": item["snippet"]["resourceId"]["channelId"],
                    "channelName": item["snippet"]["title"],
                    "thumbnailUrl": item["snippet"]["thumbnails"]["default"]["url"],
                    "lastUploadDate": "pending",
                    "isSubscribed": True,
                })
            next_page_token = res.get("nextPageToken")
            if not next_page_token: break
        return jsonify(all_subscriptions)
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze_channel():
    youtube = build_youtube_service()
    if not youtube: return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json()
    channel_id = data.get('channelId')
    try:
        ch_res = youtube.channels().list(part="contentDetails", id=channel_id).execute()
        if not ch_res.get("items"): return jsonify({"channelId": channel_id, "lastUploadDate": None})
        uploads_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl_res = youtube.playlistItems().list(part="snippet", playlistId=uploads_id, maxResults=1).execute()
        last_date = pl_res["items"][0]["snippet"]["publishedAt"] if pl_res.get("items") else None
        return jsonify({"channelId": channel_id, "lastUploadDate": last_date})
    except:
        return jsonify({"channelId": channel_id, "lastUploadDate": None})

@app.route('/api/subscriptions/<subscription_id>', methods=['DELETE'])
def delete_subscription(subscription_id):
    youtube = build_youtube_service()
    if not youtube: return jsonify({"error": "Not authenticated"}), 401
    try:
        youtube.subscriptions().delete(id=subscription_id).execute()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/api/subscriptions/bulk-delete', methods=['POST'])
def bulk_delete_subscriptions():
    youtube = build_youtube_service()
    if not youtube: return jsonify({"error": "Not authenticated"}), 401
    ids = request.get_json().get('subscriptionIds', [])
    success = 0
    for sub_id in ids:
        try:
            youtube.subscriptions().delete(id=sub_id).execute()
            success += 1
        except: pass
    return jsonify({"successCount": success, "failCount": len(ids) - success})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
