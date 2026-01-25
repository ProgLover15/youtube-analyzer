import os
import logging
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
from flask import Flask, redirect, request, session, url_for, jsonify, Response
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# ログ設定: 予期せぬエラー時に原因を追えるようにします
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

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

# カテゴリマップの最適化
CATEGORY_MAP = {
    "1": "映画/アニメ", "2": "自動車", "10": "音楽", "15": "ペット", "17": "スポーツ",
    "19": "旅行", "20": "ゲーム", "22": "ブログ", "23": "コメディ", "24": "エンタメ",
    "25": "ニュース", "26": "ハウツー", "27": "教育", "28": "科学/技術", "29": "非営利"
}

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

# 共通フロー生成
def create_flow():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        {"web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [os.getenv("REDIRECT_URI")]
        }}, scopes=SCOPES)
    flow.redirect_uri = os.getenv("REDIRECT_URI")
    return flow

@app.route('/login')
def login():
    session.clear()
    flow = create_flow()
    # prompt='select_account' でご希望の選択画面を強制
    auth_url, _ = flow.authorization_url(prompt='select_account', access_type='offline')
    return redirect(auth_url)

@app.route('/callback')
def callback():
    flow = create_flow()
    flow.fetch_token(authorization_response=request.url.replace('http://', 'https://'))
    creds = flow.credentials
    session['credentials'] = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes
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
    # 認証情報の読み込み。有効期限切れを考慮
    creds = google.oauth2.credentials.Credentials(**session['credentials'])
    return googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=creds)

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
            c_res = y.channels().list(part="statistics,snippet", id=",".join(ids)).execute()
            c_map = {c['id']: c for c in c_res.get('items', [])}
            
            for i in items:
                cid = i['snippet']['resourceId']['channelId']
                info = c_map.get(cid, {'statistics': {}, 'snippet': {}})
                all_subs.append({
                    "subscriptionId": i['id'],
                    "channelId": cid,
                    "title": i['snippet']['title'],
                    "thumbnails": i['snippet']['thumbnails']['default']['url'],
                    "lastUploadDate": "pending",
                    "subscribers": int(info['statistics'].get('subscriberCount', 0)),
                    "videoCount": int(info['statistics'].get('videoCount', 0)),
                    "category": CATEGORY_MAP.get(info['snippet'].get('categoryId', ""), "その他")
                })
            token = res.get('nextPageToken')
            if not token: break
        return jsonify(all_subs)
    except Exception as e:
        logger.error(f"Error fetching channels: {e}")
        return jsonify([]), 500

@app.route('/api/analyze', methods=['POST'])
def analyze():
    y = build_service()
    if not y: return jsonify({"error": "Unauthorized"}), 401
    cid = request.get_json().get('channelId')
    try:
        c = y.channels().list(part="contentDetails", id=cid).execute()
        up_id = c["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        p = y.playlistItems().list(part="snippet", playlistId=up_id, maxResults=1).execute()
        if p.get("items"):
            return jsonify({"lastUploadDate": p["items"][0]["snippet"]["publishedAt"]})
        return jsonify({"lastUploadDate": "none"})
    except Exception as e:
        logger.error(f"Error analyzing channel {cid}: {e}")
        return jsonify({"lastUploadDate": "none"})

@app.route('/api/subscriptions/bulk-delete', methods=['POST'])
def bulk_delete():
    y = build_service()
    if not y: return jsonify({"error": "Unauthorized"}), 401
    ids = request.get_json().get('subscriptionIds', [])
    s, f = 0, 0
    for sid in ids:
        try:
            y.subscriptions().delete(id=sid).execute()
            s += 1
        except Exception as e:
            logger.error(f"Error deleting sub {sid}: {e}")
            f += 1
    return jsonify({"success": s, "fail": f})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
