import os
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from flask import Flask, redirect, request, session, url_for, jsonify, send_from_directory
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

# --- アプリケーション設定 ---
# static_folder='.' は、index.htmlと同じ階層にapp.pyを置くことを想定しています。
app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv("FLASK_SECRET_KEY")
# 開発環境でのHTTP通信を許可（本番環境ではHTTPSを使用してください）
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# --- Google API 設定 ---
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
# 以前のエラーを修正するため、readonlyスコープも許可します。
SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly"
]
# .envファイルから読み込んだ情報でクライアント設定を構築
CLIENT_SECRETS_FILE = {
    "web": {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        # このリダイレクトURIはGoogle Cloud Consoleにも必ず登録してください
        "redirect_uris": ["http://127.0.0.1:5000/auth/callback"]
    }
}

# --- ヘルパー関数 ---
def build_youtube_service():
    """セッション情報からYouTube APIサービスを構築する"""
    if 'credentials' not in session:
        return None
    # セッションから復元するために google.oauth2.credentials をインポート
    from google.oauth2.credentials import Credentials
    # 辞書形式で保存した認証情報をCredentialsオブジェクトに戻す
    credentials = Credentials(**session['credentials'])
    return googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials)

# --- フロントエンド提供ルート ---
@app.route('/')
def index():
    """index.htmlを提供する"""
    return send_from_directory('.', 'index.html')

# --- 認証ルート ---
@app.route('/auth/google')
def auth_google():
    """Googleへの認証を開始する"""
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    # サーバー上のコールバックURLを動的に生成
    flow.redirect_uri = url_for('auth_callback', _external=True)
    authorization_url, state = flow.authorization_url(
        access_type='offline', include_granted_scopes='true')
    # CSRF対策のためにstateをセッションに保存
    session['state'] = state
    return redirect(authorization_url)

@app.route('/auth/callback')
def auth_callback():
    """Googleからのコールバックを処理する"""
    state = session['state']
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
    flow.redirect_uri = url_for('auth_callback', _external=True)

    authorization_response = request.url
    flow.fetch_token(authorization_response=authorization_response)

    credentials = flow.credentials
    # セッションに保存できる辞書形式に変換
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    # 認証完了後、トップページにリダイレクト
    return redirect(url_for('index'))

@app.route('/api/auth/status')
def auth_status():
    """ログイン状態を確認する"""
    if 'credentials' in session:
        return jsonify({"status": "authenticated"})
    return jsonify({"error": "Not authenticated"}), 401

# --- APIエンドポイント ---
@app.route('/api/all-channels')
def get_all_channels():
    """全ての登録チャンネルを取得する"""
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401

    all_subscriptions = []
    next_page_token = None
    try:
        # nextPageTokenがなくなるまで繰り返し取得
        while True:
            request = youtube.subscriptions().list(
                part="snippet",
                mine=True,
                maxResults=50, # 一度に取得できる最大数
                pageToken=next_page_token
            )
            response = request.execute()

            for item in response.get("items", []):
                all_subscriptions.append({
                    "subscriptionId": item["id"],
                    "channelId": item["snippet"]["resourceId"]["channelId"],
                    "channelName": item["snippet"]["title"],
                    "thumbnailUrl": item["snippet"]["thumbnails"]["default"]["url"],
                    "lastUploadDate": "pending", # フロントエンドで分析待ち状態を示す
                    "isSubscribed": True,
                })

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break # 次のページがなければループを抜ける
        return jsonify(all_subscriptions)

    except googleapiclient.errors.HttpError as e:
        return jsonify({"message": f"An API error occurred: {e}"}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze_channel():
    """チャンネルの最終投稿日を分析する"""
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json()
    channel_id = data.get('channelId')
    if not channel_id:
        return jsonify({"message": "channelId is required"}), 400

    try:
        # 1. チャンネル情報からuploadsプレイリストIDを取得
        channel_request = youtube.channels().list(
            part="contentDetails",
            id=channel_id
        )
        channel_response = channel_request.execute()
        # チャンネルが存在しない、または非公開の場合
        if not channel_response.get("items"):
            return jsonify({"channelId": channel_id, "lastUploadDate": None})

        uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # 2. プレイリストから最新の動画を1件取得
        playlist_request = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=1
        )
        playlist_response = playlist_request.execute()

        last_upload_date = None
        # プレイリストに動画があれば投稿日を取得
        if playlist_response.get("items"):
            last_upload_date = playlist_response["items"][0]["snippet"]["publishedAt"]

        return jsonify({
            "channelId": channel_id,
            "lastUploadDate": last_upload_date
        })
    except Exception as e:
        # その他の理由で分析に失敗した場合（権限がないなど）
        return jsonify({
            "channelId": channel_id,
            "lastUploadDate": None # 失敗した場合はnullを返す
        })

@app.route('/api/subscriptions/<subscription_id>', methods=['DELETE'])
def delete_subscription(subscription_id):
    """チャンネル登録を解除する"""
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
    """複数のチャンネル登録を一括解除する"""
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

# --- サーバー起動 ---
if __name__ == '__main__':
    # debug=True にすると、コードの変更時にサーバーが自動で再起動します
    app.run(debug=True, port=5000)
