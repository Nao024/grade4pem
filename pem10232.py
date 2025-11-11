# -*- coding: utf-8 -*-
import streamlit as st
import os
import json
from datetime import datetime
from openai import OpenAI
import pytz
import base64
import requests

# ========== 初期設定 ==========
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
USER_FILE = "users.json"
LOG_DIR = "log"
os.makedirs(LOG_DIR, exist_ok=True)

##REPO_OWNER: アカウント名, REPO_NAME: リポジトリ名
GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
REPO_OWNER = st.secrets["REPO_OWNER"]
REPO_NAME  = st.secrets["REPO_NAME"]

GITHUB_API_BASE = "https://api.github.com"

USER_FILE_PATH = "users.json"

LOG_DIR = "logs"

def timestamp_jst_iso():
    """日本時間(Asia/Tokyo)の現在時刻を返す"""
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S")

def filename_timestamp_jst_iso():
    """日本時間(Asia/Tokyo)の現在時刻を返す"""
    tz = pytz.timezone("Asia/Tokyo")
    now = datetime.now(tz)
    return now.strftime("%Y%m%d_%H%M%S")
    
# ========== GitHub 連携 ==========
def get_github_file(owner: str, repo: str, path: str):
    """
    GitHub上のファイルを取得し、JSON(dict)を返す。
    返り値の例:
      {
        "content": "<base64...>",
        "sha": "...",
        ...
      }
    ファイルがない場合は None を返す。
    エラー時は st.error() で通知して None を返す。
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json()
    elif r.status_code == 404:
        # まだ存在しない
        return None
    else:
        st.error(f"GitHub API error (GET {path}): {r.status_code} {r.text}")
        return None
        
def append_line_to_repo_log(owner: str, repo: str, path: str, event_text: str):
    """
    指定のevent_textを1行として、GitHub上の logs/app_log.txt に追記する。
    仕組み:
      1. いまのファイルをGET
      2. デコードして末尾に event_text+"\n" を足す
      3. 再エンコードして PUT でアップロード
    新規ファイルの場合は、新しく作る。
    """
    # 1行分を "event_text" の形式で整える
    #now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{event_text}"

    existing = get_github_file(owner, repo, path)

    if existing is None:
        # ファイルが存在しない場合は新規作成
        updated_text = line + "\n"
        sha = None
    else:
        # 既存ファイルあり -> もとのcontentを取り出して追記
        b64_content = existing["content"]
        decoded = base64.b64decode(b64_content).decode("utf-8")
        updated_text = decoded + line + "\n"
        sha = existing["sha"]

    # base64エンコード
    b64_updated = base64.b64encode(updated_text.encode("utf-8")).decode("utf-8")

    # PUTで更新
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "message": f"Append log at {timestamp_jst_iso()}",
        "content": b64_updated,
    }
    if sha:
        payload["sha"] = sha  # 既存ファイル更新時に必須

    r = requests.put(url, headers=headers, json=payload)

    if r.status_code not in (200, 201):
        st.error(f"GitHub API error (PUT {path}): {r.status_code} {r.text}")


# ========== ユーザー管理 ==========
def load_users() -> dict:
    """
    users.json をGitHubから読み込んで dict を返す。
    ない場合は {} を返す。
    """
    existing = get_github_file(REPO_OWNER, REPO_NAME, USER_FILE_PATH)
    if existing is None:
        return {}
    try:
        decoded = base64.b64decode(existing["content"]).decode("utf-8")
        data = json.loads(decoded)
        if isinstance(data, dict):
            return data
        else:
            st.warning("users.json が不正形式のため、空辞書として扱います。")
            return {}
    except Exception as e:
        st.error(f"users.json の読み込みに失敗: {e}")
        return {}

def save_users(users: dict, commit_message: str):
    """
    users(dict) を users.json に保存（新規 or 更新）
    """
    # 既存のSHAを取る
    existing = get_github_file(REPO_OWNER, REPO_NAME, USER_FILE_PATH)
    sha = existing["sha"] if existing is not None else None

    json_text = json.dumps(users, ensure_ascii=False, indent=2) + "\n"
    b64_updated = base64.b64encode(json_text.encode("utf-8")).decode("utf-8")

    url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/contents/{USER_FILE_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }
    #now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "message": f"{commit_message} at {timestamp_jst_iso()}",
        "content": b64_updated,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=headers, json=payload)
    if r.status_code not in (200, 201):
        st.error(f"GitHub API error (PUT {USER_FILE_PATH}): {r.status_code} {r.text}")
    else:
        st.success("users.json をGitHubに保存しました。")


# ========== ログ記録 ==========
def write_log(message):
    now = timestamp_jst_iso()
    github_log_path = os.path.join(LOG_DIR, "IDlogin.txt")
    with open(github_log_path, "a", encoding="utf-8") as f:
        f.write(f"[{now}] {message}\n")

# ========== ログイン機能 ==========
if "page" not in st.session_state:
    st.session_state.page = "login"
if "user_id" not in st.session_state:
    st.session_state.user_id = None

users = load_users()

def login_page():
    st.title("🔐 ログインページ")

    # それぞれに一意のキーを付与
    id_input = st.text_input("ユーザーID", key="login_id_input")
    pw_input = st.text_input("パスワード", type="password", key="login_pw_input")

    if st.button("ログイン", key="login_button"):
        if id_input in users and users[id_input] == pw_input:
            st.session_state.page = "main"
            st.session_state.user_id = id_input
            github_log_path = LOG_DIR + "/IDlogin.txt"
            append_line_to_repo_log(REPO_OWNER, REPO_NAME, github_log_path, f"[{timestamp_jst_iso()}] ログイン: {id_input}")
            st.success(f"{id_input} さん、ようこそ！")
            st.rerun()
        else:
            st.error("IDまたはパスワードが間違っています。")

    st.markdown("---")
    if st.button("初回登録", key="to_register_button"):
        st.session_state.page = "register"
        st.rerun()



def register_page():
    st.title("📝 初回登録ページ")

    # こちらもユニークキーを付与
    new_id = st.text_input("新しいユーザーIDを入力", key="register_id_input")
    new_pw = st.text_input("パスワードを入力", type="password", key="register_pw_input")

    if st.button("登録", key="register_button"):
        if new_id in users:
            st.error("このIDはすでに登録されています。")
        elif not new_id or not new_pw:
            st.error("IDとパスワードを入力してください。")
        else:
            users[new_id] = new_pw
            save_users(users, commit_message=f"Add user {new_id}")
            st.success("登録が完了しました！ログイン画面に戻ります。")
            st.session_state.page = "login"
            st.rerun()

    if st.button("ログイン画面に戻る", key="to_login_button"):
        st.session_state.page = "login"
        st.rerun()


# ========== メインアプリ（既存のプログラム） ==========
def main_page():
    st.sidebar.write(f"👤 ログイン中: {st.session_state.user_id}")
    if st.sidebar.button("ログアウト"):
        github_log_path = f"{LOG_DIR}/IDlogin.txt"
        append_line_to_repo_log(REPO_OWNER, REPO_NAME, github_log_path, f"[{timestamp_jst_iso()}] ログアウト: {st.session_state.user_id}")
        st.session_state.page = "login"
        st.session_state.user_id = None
        st.warning("ログアウトしました。")
        st.rerun()

    st.title("AIによるプログラムエラー診断ツール")

    # --- 入力エリア ---
    st.header("① ファイルと情報の入力")
    program = st.file_uploader("Javaプログラム（.java）をアップロード", type=["java"], accept_multiple_files=True)
    testcase = st.file_uploader("テストケース（任意）をアップロード", type=["java"], accept_multiple_files=True)
    pem = st.file_uploader("PEMファイル（任意）をアップロード", type=["txt"], accept_multiple_files=True)

    # --- 条件選択 ---
    st.header("② 条件を選択")
    test_opt = st.radio("テストケースの有無", ["あり", "なし"], horizontal=True)
    error_opt = st.selectbox("指摘するエラー数", ["１つだけ", "できるだけたくさん", "指定なし"])
    level_opt = st.radio("解説レベル", ["初級", "中級", "上級"], horizontal=True)

    # --- プロンプト生成 ---
    def build_prompt(tcase, err, level):
        common = "次のプログラムについて、テストケースが成功するようにエラーの修正方法を"
        audience = {"初級": "専門用語を使わずに", "中級": "大学生向けに", "上級": "技術的に詳しく"}
        target = audience[level]

        prompt = f"{common}{target}説明してください。"
        if err == "１つだけ":
            prompt += "エラーが複数ある場合は、最も重要なものを1つ挙げてください。"
        elif err == "できるだけたくさん":
            prompt += "修正箇所をできるだけ多く挙げてください。"
        if tcase == "あり":
            prompt += "テストケースの結果も全て表示してください。"
        return prompt

    selected_prompt = build_prompt(test_opt, error_opt, level_opt)

    # --- 出力 ---
    st.header("③ 選択されたプロンプト")
    st.code(selected_prompt, language="markdown")

    # --- 実行ボタン ---
    if st.button("AIに送信"):
        if not program:
            st.error("Javaプログラムをアップロードしてください。")
        else:
            write_log(f"実行: {st.session_state.user_id} がAI診断を実行")
            st.success("以下の条件でAIに送信しました。")
            st.write({
                "テストケース": test_opt,
                "指摘数": error_opt,
                "解説レベル": level_opt
            })
            st.write("使用プロンプト:")
            st.code(selected_prompt, language="markdown")

            st.info("AIが解析中です。しばらくお待ちください…")

            program_text = "".join(f"\n\n【{p.name}】\n{p.read().decode('utf-8')}" for p in program)
            testcase_text = "".join(f"\n\n【{t.name}】\n{t.read().decode('utf-8')}" for t in testcase) if testcase else ""
            pem_text = "".join(f"\n\n【{pe.name}】\n{pe.read().decode('utf-8')}" for pe in pem) if pem else ""


            full_prompt = f"{selected_prompt}\n\n【プログラム】\n{program_text}\n\n【テストケース】\n{testcase_text}\n【PEM】{pem_text}"

            try:
                response = client.chat.completions.create(
                    model="gpt-5",
                    messages=[
                        {"role": "system", "content": "あなたは熟練したJava講師です。"},
                        {"role": "user", "content": full_prompt}
                    ]
                )

                result = response.choices[0].message.content
                st.success(" AIの解析が完了しました！")
                st.subheader("④ AIの解析結果")
                st.markdown(result)

                # --- ログ記録（解析結果も） ---
                github_log_path = os.path.join(LOG_DIR, f"log_{filename_timestamp_jst_iso()}.txt")
                
                msg = f"[ユーザー]: {st.session_state.user_id}\n"
                msg += f"[日時]: {timestamp_jst_iso()}\n\n"
                msg += "=== 入力情報 ===\n"
                program_names = [p.name for p in program] if program else []
                test_names = [t.name for t in testcase] if testcase else []
                pem_names = [pe.name for pe in pem] if pem else []
                msg += f"[プログラムファイル]: {', '.join(program_names)}\n"
                msg += f"[テストファイル]: {', '.join(test_names) or 'なし'}\n"
                msg += f"PEM: {', '.join(pem_names) or 'なし'}\n"
                msg += f"[テスト有無]: {test_opt}\n"
                msg += f"[エラー数指定]: {error_opt}\n"
                msg += f"[解説レベル]: {level_opt}\n"
                msg += "=== プロンプト ===\n"
                msg += f"{selected_prompt}\n\n"
                msg += "=== 解析結果 ===\n"
                msg += result
                
                # GitHubにも追記
                append_line_to_repo_log(REPO_OWNER, REPO_NAME, github_log_path, msg)

            except Exception as e:
                st.error(f"AI解析中にエラーが発生しました: {e}")

# ========== ページ遷移制御 ==========
if st.session_state.page == "login":
    login_page()
elif st.session_state.page == "register":
    register_page()
elif st.session_state.page == "main":
    main_page()
