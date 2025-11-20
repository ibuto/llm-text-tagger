import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
import openai  # OpenAI APIライブラリを使用

app = Flask(__name__)
app.secret_key = 'secsec'  # flashメッセージのために必要

# --- 設定・データファイルのパス ---
INPUTS_DIR = 'inputs'
OUTPUTS_DIR = 'outputs'
TAGS_FILE = 'tags.json'
SETTINGS_FILE = 'settings.json'

# --- ディレクトリ・ファイルの初期化 ---
os.makedirs(INPUTS_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)
if not os.path.exists(TAGS_FILE):
    with open(TAGS_FILE, 'w', encoding='utf-8') as f:
        json.dump({}, f)
if not os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            "api_base": "http://127.0.0.1:1234/v1",
            "api_key": "lm-studio",
            "system_prompt": "あなたは優秀なドキュメント分析アシスタントです。\n以下のドキュメントの内容を分析し、関連するタグを提示されたタグリストの中からすべて選んで、カンマ区切りで出力してください。\n\n#利用可能なタグリスト\n```\n%TAGS%\n```\n\n#ドキュメント"
        }, f, indent=4)

# --- ヘルパー関数 ---
def load_json(file_path):
    """JSONファイルを読み込む"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(data, file_path):
    """JSONファイルに書き込む"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_llm_client():
    """設定に基づいてOpenAIクライアントを取得する"""
    settings = load_json(SETTINGS_FILE)
    return openai.OpenAI(
        base_url=settings.get('api_base'),
        api_key=settings.get('api_key'),
    )

# --- ルーティング ---

@app.route('/')
def index():
    """メインページ。追加タブをデフォルトで表示"""
    return redirect(url_for('add_files'))

# --- 追加タブ ---
@app.route('/add', methods=['GET', 'POST'])
def add_files():
    if request.method == 'POST':
        if 'files[]' not in request.files:
            flash('ファイルが選択されていません')
            return redirect(request.url)
        files = request.files.getlist('files[]')
        for file in files:
            if file and file.filename.endswith('.txt'):
                filename = file.filename
                file.save(os.path.join(INPUTS_DIR, filename))
        flash('ファイルが正常にアップロードされました')
        return redirect(url_for('add_files'))

    input_files = os.listdir(INPUTS_DIR)
    output_files = os.listdir(OUTPUTS_DIR)
    unprocessed_files = [f for f in input_files if f not in output_files]
    return render_template('add.html', unprocessed_files=unprocessed_files)

@app.route('/process_files', methods=['POST'])
def process_files():
    """タグ付け処理を実行する"""
    try:
        client = get_llm_client()
        tags_data = load_json(TAGS_FILE)
        settings = load_json(SETTINGS_FILE)

        # %TAGS% 変数を準備
        tags_list_str = ""
        for tag_name, data in tags_data.items():
            variants = [tag_name] + data.get('variant', [])
            tags_list_str += f"{tag_name}: {','.join(variants)}\n"

        # %DATE% 変数を準備
        current_time = datetime.now().strftime('%Y/%m/%d %H:%M:%S')

        # システムプロンプトの変数を置換
        system_prompt = settings['system_prompt']
        system_prompt = system_prompt.replace('%TAGS%', tags_list_str)
        system_prompt = system_prompt.replace('%DATE%', current_time)

        # 未処理のファイルを取得
        input_files = os.listdir(INPUTS_DIR)
        output_files = os.listdir(OUTPUTS_DIR)
        unprocessed_files = [f for f in input_files if f not in output_files]

        for filename in unprocessed_files:
            # 1. ファイル読み込み
            with open(os.path.join(INPUTS_DIR, filename), 'r', encoding='utf-8') as f:
                content = f.read()

            # 2. LLMによるタグ付け
            response = client.chat.completions.create(
                model="local-model",  # モデル名は適宜変更
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ],
                temperature=0.0
            )
            llm_output = response.choices[0].message.content.strip()
            
            # 3. LLMの回答からタグを抽出
            extracted_tags = [tag.strip() for tag in llm_output.split(',') if tag.strip() in tags_data]

            # 4. 表記ゆれ修正
            corrected_content = content
            for tag_name, data in tags_data.items():
                for variant in data.get('variant', []):
                    corrected_content = corrected_content.replace(variant, tag_name)

            # 5. 出力ファイル生成
            output_content = f"タグ: {', '.join(extracted_tags)}\n{corrected_content}"
            with open(os.path.join(OUTPUTS_DIR, filename), 'w', encoding='utf-8') as f:
                f.write(output_content)

        flash(f'{len(unprocessed_files)}件のファイルのタグ付けが完了しました。')
    except Exception as e:
        flash(f'エラーが発生しました: {e}')

    return redirect(url_for('add_files'))

# --- 閲覧タブ ---
@app.route('/view')
def view_files():
    output_files = os.listdir(OUTPUTS_DIR)
    return render_template('view.html', files=output_files)

@app.route('/view/<filename>')
def view_file_content(filename):
    """ファイル内容を表示"""
    filepath = os.path.join(OUTPUTS_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return render_template('view_detail.html', filename=filename, content=content)
    return redirect(url_for('view_files'))

@app.route('/delete_output/<filename>', methods=['POST'])
def delete_output_file(filename):
    """出力ファイルを削除"""
    filepath = os.path.join(OUTPUTS_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        flash(f'{filename} を削除しました。')
    return redirect(url_for('view_files'))


# --- タグ管理タブ ---
@app.route('/tags', methods=['GET', 'POST'])
def tag_management():
    tags_data = load_json(TAGS_FILE)
    if request.method == 'POST':
        tag_name = request.form.get('tagName')
        variants = request.form.get('variants', '')
        if tag_name:
            tags_data[tag_name] = {
                "tagName": tag_name,
                "variant": [v.strip() for v in variants.split(',') if v.strip()]
            }
            save_json(tags_data, TAGS_FILE)
            flash(f'タグ "{tag_name}" を追加/更新しました。')
        return redirect(url_for('tag_management'))
    
    return render_template('tag_management.html', tags=tags_data)

@app.route('/delete_tag/<tag_name>', methods=['POST'])
def delete_tag(tag_name):
    tags_data = load_json(TAGS_FILE)
    if tag_name in tags_data:
        del tags_data[tag_name]
        save_json(tags_data, TAGS_FILE)
        flash(f'タグ "{tag_name}" を削除しました。')
    return redirect(url_for('tag_management'))

# --- 設定タブ ---
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        new_settings = {
            "api_base": request.form.get('api_base'),
            "api_key": request.form.get('api_key'),
            "system_prompt": request.form.get('system_prompt')
        }
        save_json(new_settings, SETTINGS_FILE)
        flash('設定を保存しました。')
        return redirect(url_for('settings'))

    current_settings = load_json(SETTINGS_FILE)
    return render_template('settings.html', settings=current_settings)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
