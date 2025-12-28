import os
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from flask import Flask, redirect, request, session, url_for, jsonify, send_from_directory
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix # 追加: 本番環境でのHTTPS対応用

# .envファイルから環境変数を読み込む
load_dotenv()

# --- アプリケーション設定 ---
app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# 【修正点1】Renderなどの本番環境では、プロキシ経由であることをアプリに教える必要があります
# これにより、url_forが自動的に 'https://' のURLを生成するようになります。
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# 【修正点2】Googleが余分なスコープ(email等)を返してきてもエラーにしない設定
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

# 【修正点3】ローカル開発環境以外（Render上など）ではHTTPSを強制するため、
# OAUTHLIB_INSECURE_TRANSPORT は削除するか、ローカル判定を入れるのがベターです。
# Render上ではこの行はコメントアウトするか削除してください。
# os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1" 

# --- Google API 設定 ---
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
        # 注: ここは app.route('/auth/google') 内で動的に生成されるため、辞書内では重要ではありませんが、
        # Google Cloud Console の「承認済みのリダイレクト URI」には
        # https://<あなたのRenderアプリ名>.onrender.com/auth/callback
        # を登録しておく必要があります。
        "redirect_uris": ["http://127.0.0.1:5000/auth/callback"] 
    }
}

# --- ヘルパー関数 ---
def build_youtube_service():
    """セッション情報からYouTube APIサービスを構築する"""
    if 'credentials' not in session:
        return None
    from google.oauth2.credentials import Credentials
    credentials = Credentials(**session['credentials'])
    return googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)

# --- フロントエンド提供ルート ---
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# --- 認証ルート ---
@app.route('/auth/google')
def auth_google():
    """Googleへの認証を開始する"""
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    
    # 【重要】_external=Trueにより、現在のスキーム(https)に合わせた絶対URLが生成されます
    flow.redirect_uri = url_for('auth_callback', _external=True)
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        # 強制的に承認画面を出したい場合は以下を有効化
        # prompt='consent' 
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/auth/callback')
def auth_callback():
    """Googleからのコールバックを処理する"""
    state = session['state']
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    
    # ここでも同じRedirect URIを指定する必要があります
    flow.redirect_uri = url_for('auth_callback', _external=True)

    # httpsへの強制変換（念の為の安全策）
    # Render等の背後では request.url が http で来ることがあるため、httpsに置換
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

@app.route('/api/auth/status')
def auth_status():
    if 'credentials' in session:
        return jsonify({"status": "authenticated"})
    return jsonify({"error": "Not authenticated"}), 401

# --- APIエンドポイント (変更なし) ---
@app.route('/api/all-channels')
def get_all_channels():
    # ... (元のコードのまま)
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401

    all_subscriptions = []
    next_page_token = None
    try:
        while True:
            request = youtube.subscriptions().list(
                part="snippet",
                mine=True,
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()

            for item in response.get("items", []):
                all_subscriptions.append({
                    "subscriptionId": item["id"],
                    "channelId": item["snippet"]["resourceId"]["channelId"],
                    "channelName": item["snippet"]["title"],
                    "thumbnailUrl": item["snippet"]["thumbnails"]["default"]["url"],
                    "lastUploadDate": "pending",
                    "isSubscribed": True,
                })

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break
        return jsonify(all_subscriptions)

    except googleapiclient.errors.HttpError as e:
        return jsonify({"message": f"An API error occurred: {e}"}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze_channel():
    # ... (元のコードのまま)
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json()
    channel_id = data.get('channelId')
    if not channel_id:
        return jsonify({"message": "channelId is required"}), 400

    try:
        channel_request = youtube.channels().list(
            part="contentDetails",
            id=channel_id
        )
        channel_response = channel_request.execute()
        if not channel_response.get("items"):
            return jsonify({"channelId": channel_id, "lastUploadDate": None})

        uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

        playlist_request = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=1
        )
        playlist_response = playlist_request.execute()

        last_upload_date = None
        if playlist_response.get("items"):
            last_upload_date = playlist_response["items"][0]["snippet"]["publishedAt"]

        return jsonify({
            "channelId": channel_id,
            "lastUploadDate": last_upload_date
        })
    except Exception as e:
        return jsonify({
            "channelId": channel_id,
            "lastUploadDate": None
        })

@app.route('/api/subscriptions/<subscription_id>', methods=['DELETE'])
def delete_subscription(subscription_id):
    # ... (元のコードのまま)
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        youtube.subscriptions().delete(id=subscription_id).execute()
        return jsonify({"status": "success"}), 200
    except googleapiclient.errors.HttpError as e:
        return jsonify({"message": f"Failed to unsubscribe: {e}"}), 500

@app.route('/api/subscriptions/bulk-delete', methods=['POST'])
def bulk_delete_subscriptions():
    # ... (元のコードのまま)
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json()
    subscription_ids = data.get('subscriptionIds', [])
    if not subscription_ids:
        return jsonify({"message": "subscriptionIds are required"}), 400

    success_count = 0
    fail_count = 0

    for sub_id in subscription_ids:
        try:
            youtube.subscriptions().delete(id=sub_id).execute()
            success_count += 1
        except googleapiclient.errors.HttpError:
            fail_count += 1

    return jsonify({"successCount": success_count, "failCount": fail_count})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
