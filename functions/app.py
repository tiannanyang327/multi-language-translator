from flask import Flask, request, render_template, send_file, jsonify
import pandas as pd
from google.cloud import translate_v2 as translate
import io
import os
import threading
import html
import re

# 配置 Flask 应用并指定模板文件夹
app = Flask(__name__, template_folder="../templates")

# 全局变量，用于存储进度和文件信息
progress = {
    'total': 0,
    'completed': 0,
    'filename': ''
}

# 初始化 Google Cloud Translation 客户端
translate_client = translate.Client()

def replace_variables(text):
    text = re.sub(r'%@', 'PLACEHOLDER_PERCENT', text)
    text = re.sub(r'{[^}]*}', 'PLACEHOLDER_CURLY', text)
    return text

def restore_variables(text, original_text):
    # Restore %@ variables
    placeholder_percent_count = text.count('PLACEHOLDER_PERCENT')
    for _ in range(placeholder_percent_count):
        text = text.replace('PLACEHOLDER_PERCENT', '%@', 1)
    
    # Restore {variables}
    curly_matches = re.findall(r'{[^}]*}', original_text)
    for curly in curly_matches:
        text = text.replace('PLACEHOLDER_CURLY', curly, 1)
    
    return text

def translate_text(texts, target_language, batch_size=5):
    translated_texts = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            print(f"Translating batch to '{target_language}': {batch[:5]}...")  # 调试日志，仅显示前5个文本
            replaced_batch = [replace_variables(text) for text in batch]
            results = translate_client.translate(replaced_batch, target_language=target_language)
            translated_batch = [html.unescape(result['translatedText']) for result in results]
            restored_batch = [restore_variables(translated, original) for translated, original in zip(translated_batch, batch)]
            translated_texts.extend(restored_batch)
        except Exception as e:
            print(f"Error translating batch to '{target_language}': {e}")
            translated_texts.extend(batch)  # 返回原始文本以继续处理
    return translated_texts

def perform_translation(file_content, languages):
    global progress
    df = pd.read_csv(io.StringIO(file_content))
    total_translations = len(df) * len(languages)
    progress['total'] = total_translations
    progress['completed'] = 0

    print(f"Starting translation. Total translations: {total_translations}")

    for lang_code, col_name in languages.items():
        texts = df['en'].tolist()
        try:
            translated_texts = translate_text(texts, lang_code)
            df[col_name] = translated_texts
            progress['completed'] += len(texts)
            print(f"Translated {progress['completed']} of {progress['total']} for language {lang_code}")
        except Exception as e:
            print(f"Error translating to {lang_code}: {e}")

    # 定义预期的列顺序
    desired_order = ['key', 'cn', 'zh-Hant', 'en', 'ja', 'de', 'fr', 'ru', 'it', 'es', 'fi', 'he', 'ar', 'vi', 'pt', 'pl', 'tr', 'cs']
    
    # 根据预期的列顺序重新排列列
    ordered_columns = [col for col in desired_order if col in df.columns]

    output = io.StringIO()
    df.to_csv(output, index=False, columns=ordered_columns)
    output.seek(0)

    # Save the translated CSV to a file
    output_filename = 'translated_content.csv'
    output_path = os.path.join(os.getcwd(), output_filename)
    with open(output_path, 'w') as f:
        f.write(output.getvalue())

    progress['filename'] = output_filename
    print(f"Translation completed. File saved as {output_filename}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/translate', methods=['POST'])
def translate():
    global progress
    file = request.files['file']
    file_content = file.read().decode('utf-8')
    languages = {
        'zh-CN': 'cn',
        'zh-TW': 'zh-Hant',
        'en': 'en',
        'ja': 'ja',
        'de': 'de',
        'fr': 'fr',
        'ru': 'ru',
        'it': 'it',
        'es': 'es',
        'fi': 'fi',
        'he': 'he',
        'ar': 'ar',
        'vi': 'vi',
        'pt': 'pt',
        'pl': 'pl',
        'tr': 'tr',
        'cs': 'cs'
    }

    # Reset progress
    progress['total'] = 0
    progress['completed'] = 0
    progress['filename'] = ''

    translation_thread = threading.Thread(target=perform_translation, args=(file_content, languages))
    translation_thread.start()

    return jsonify({"message": "Translation started"})

@app.route('/progress', methods=['GET'])
def get_progress():
    global progress
    return jsonify(progress)

@app.route('/download', methods=['GET'])
def download():
    global progress
    output_filename = progress['filename']
    if output_filename:
        output_path = os.path.join(os.getcwd(), output_filename)
        return send_file(output_path, as_attachment=True, download_name=output_filename)
    return "No file to download", 404

if __name__ == '__main__':
    app.run(debug=True)

# Handler for Netlify Functions
def handler(event, context):
    from werkzeug.datastructures import Headers
    from werkzeug.wrappers import Request, Response
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    from werkzeug.serving import run_simple

    headers = Headers(event['headers'])
    body = event['body'] if 'body' in event else '{}'

    request = Request.from_values(
        path=event['path'],
        base_url=event['requestContext']['domainName'],
        method=event['httpMethod'],
        headers=headers,
        query_string=event['queryStringParameters'],
        data=body,
    )

    app.wsgi_app = DispatcherMiddleware(app.wsgi_app)

    response = Response.from_app(app.wsgi_app, request)

    return {
        'statusCode': response.status_code,
        'headers': dict(response.headers),
        'body': response.get_data(as_text=True),
    }