import os
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
from flask import Flask, redirect, request, session, url_for, jsonify, Response
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()
base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# Render環境でのHTTPSリダイレクト問題を解決
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)

os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
SCOPES = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.readonly"]

def get_physical_file(filename, mimetype):
    path = os.path.join(base_dir, filename)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return Response(f.read(), mimetype=mimetype)
    return "Not Found", 404

@app.route('/')
def index(): return get_physical_file('index.html', 'text/html')

@app.route('/script.js')
def serve_js(): return get_physical_file('script.js', 'application/javascript')

@app.route('/login')
def login():
    session.clear()
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        {"web": {"client_id": os.getenv("GOOGLE_CLIENT_ID"), "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                 "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
                 "redirect_uris": [os.getenv("REDIRECT_URI")]}}, scopes=SCOPES)
    flow.redirect_uri = os.getenv("REDIRECT_URI")
    auth_url, _ = flow.authorization_url(prompt='select_account', access_type='offline', include_granted_scopes='true')
    return redirect(auth_url)

@app.route('/callback')
def callback():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        {"web": {"client_id": os.getenv("GOOGLE_CLIENT_ID"), "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                 "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
                 "redirect_uris": [os.getenv("REDIRECT_URI")]}}, scopes=SCOPES)
    flow.redirect_uri = os.getenv("REDIRECT_URI")
    flow.fetch_token(authorization_response=request.url.replace('http://', 'https://'))
    session['credentials'] = {
        'token': flow.credentials.token, 'refresh_token': flow.credentials.refresh_token,
        'token_uri': flow.credentials.token_uri, 'client_id': flow.credentials.client_id,
        'client_secret': flow.credentials.client_secret, 'scopes': flow.credentials.scopes
    }
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/auth/status')
def auth_status(): return jsonify({"ok": 'credentials' in session})

def build_service():
    if 'credentials' not in session: return None
    creds = google.oauth2.credentials.Credentials(**session['credentials'])
    return googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=creds)

@app.route('/api/user/info')
def get_user_info():
    y = build_service()
    if not y: return jsonify({"ok": False}), 401
    try:
        res = y.channels().list(part="snippet", mine=True).execute()
        item = res['items'][0]['snippet']
        return jsonify({"ok": True, "name": item['title'], "icon": item['thumbnails']['default']['url']})
    except: return jsonify({"ok": False}), 500

@app.route('/api/all-channels')
def get_all_channels():
    y = build_service()
    if not y: return jsonify([]), 401
    all_subs = []
    try:
        token = None
        while True:
            res = y.subscriptions().list(part="snippet", mine=True, maxResults=50, pageToken=token).execute()
            items = res.get('items', [])
            if not items: break
            ids = [i['snippet']['resourceId']['channelId'] for i in items]
            c_res = y.channels().list(part="statistics", id=",".join(ids)).execute()
            c_map = {c['id']: c for c in c_res.get('items', [])}
            for i in items:
                cid = i['snippet']['resourceId']['channelId']
                info = c_map.get(cid, {'statistics': {}})
                all_subs.append({
                    "subscriptionId": i['id'], "channelId": cid, "title": i['snippet']['title'],
                    "thumbnails": i['snippet']['thumbnails']['default']['url'], "lastUploadDate": "pending",
                    "subscribers": int(info['statistics'].get('subscriberCount', 0))
                })
            token = res.get('nextPageToken')
            if not token: break
        return jsonify(all_subs)
    except: return jsonify([])

@app.route('/api/analyze', methods=['POST'])
def analyze():
    y = build_service()
    cid = request.get_json().get('channelId')
    try:
        c = y.channels().list(part="contentDetails", id=cid).execute()
        up_id = c["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        p = y.playlistItems().list(part="snippet", playlistId=up_id, maxResults=1).execute()
        return jsonify({"lastUploadDate": p["items"][0]["snippet"]["publishedAt"]})
    except: return jsonify({"lastUploadDate": "none"})

@app.route('/api/subscriptions/bulk-delete', methods=['POST'])
def bulk_delete():
    y = build_service()
    ids = request.get_json().get('subscriptionIds', [])
    s, f = 0, 0
    for sid in ids:
        try: y.subscriptions().delete(id=sid).execute(); s += 1
        except: f += 1
    return jsonify({"success": s, "fail": f})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
