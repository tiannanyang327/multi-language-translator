from flask import Flask, request, render_template, send_file, jsonify
import pandas as pd
from google.cloud import translate_v2 as translate
import io
import os
import threading
import html
import re
from datetime import datetime

app = Flask(__name__)

# 全局变量，用于存储进度和文件信息
progress = {
    'total': 0,
    'completed': 0,
    'filename': '',
    'finished': False
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

def translate_text(texts, target_language, source_language, batch_size=5):
    translated_texts = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            print(f"Translating batch from '{source_language}' to '{target_language}': {batch[:5]}...")  # 调试日志，仅显示前5个文本
            replaced_batch = [replace_variables(text) for text in batch]
            results = translate_client.translate(replaced_batch, target_language=target_language, source_language=source_language)
            translated_batch = [html.unescape(result['translatedText']) for result in results]
            restored_batch = [restore_variables(translated, original) for translated, original in zip(translated_batch, batch)]
            translated_texts.extend(restored_batch)
        except Exception as e:
            print(f"Error translating batch to '{target_language}': {e}")
            translated_texts.extend(batch)  # 返回原始文本以继续处理
    return translated_texts

def perform_translation(file_content, languages, target):
    global progress
    df = pd.read_csv(io.StringIO(file_content))
    total_translations = len(df) * len(languages)
    progress['total'] = total_translations
    progress['completed'] = 0
    progress['finished'] = False

    print(f"Starting translation. Total translations: {total_translations}")

    has_cn = 'cn' in df.columns

    for lang_code, col_name in languages.items():
        if col_name == 'cn':
            if has_cn:
                # 保留原始简体中文内容
                df[col_name] = df['cn']
            else:
                # 翻译简体中文内容
                texts = df['en'].tolist()
                translated_texts = translate_text(texts, 'zh-CN', 'en')
                df[col_name] = translated_texts
                progress['completed'] += len(texts)
        else:
            if has_cn and lang_code in ['zh-TW', 'ja']:
                texts = df['cn'].tolist()  # 使用简体中文列作为源文本
                source_language = 'zh-CN'
            else:
                texts = df['en'].tolist()  # 使用英文列作为源文本
                source_language = 'en'

            try:
                translated_texts = translate_text(texts, lang_code, source_language)
                df[col_name] = translated_texts
                progress['completed'] += len(texts)
                print(f"Translated {progress['completed']} of {progress['total']} for language {lang_code}")
            except Exception as e:
                print(f"Error translating to {lang_code}: {e}")

    # 根据目标类型增加额外的列
    if target == 'app':
        df['namespace'] = ''
        df['type'] = ''
        df['description'] = ''
    elif target == 'backend':
        if 'he' in df.columns:
            df['iw'] = df['he']
        if 'cs' in df.columns:
            df['sv'] = translate_text(df['en'].tolist(), 'sv', 'en')
            df['nl'] = translate_text(df['en'].tolist(), 'nl', 'en')
        df['namespace'] = ''
    elif target == 'f_app':
        # 仅需翻译 en, es, de, fr, it, pt
        desired_order = ['key', 'en', 'es', 'de', 'fr', 'it', 'pt']
        languages = {
            'es': 'es',
            'de': 'de',
            'fr': 'fr',
            'it': 'it',
            'pt': 'pt'
        }
        total_translations = len(df) * len(languages)
        progress['total'] = total_translations

        for lang_code, col_name in languages.items():
            texts = df['en'].tolist()
            translated_texts = translate_text(texts, lang_code, 'en')
            df[col_name] = translated_texts
            progress['completed'] += len(texts)
            print(f"Translated {progress['completed']} of {progress['total']} for language {lang_code}")

    # 动态生成文件名
    now = datetime.now().strftime("%Y%m%d%H%M")
    output_filename = f'update_language_{now}.csv'

    # 定义预期的列顺序
    if target == 'app':
        desired_order = ['key', 'cn', 'zh-Hant', 'en', 'ja', 'de', 'fr', 'ru', 'it', 'es', 'fi', 'he', 'ar', 'vi', 'pt', 'pl', 'tr', 'cs', 'namespace', 'type', 'description']
    elif target == 'backend':
        desired_order = ['key', 'cn', 'zh-Hant', 'en', 'ja', 'de', 'fr', 'ru', 'it', 'es', 'fi', 'he', 'iw', 'ar', 'vi', 'pt', 'pl', 'tr', 'cs', 'sv', 'nl', 'namespace']
    elif target == 'f_app':
        # 已经在之前定义
        pass
    else:
        desired_order = ['key', 'cn', 'zh-Hant', 'en', 'ja', 'de', 'fr', 'ru', 'it', 'es', 'fi', 'he', 'ar', 'vi', 'pt', 'pl', 'tr', 'cs']

    # 根据预期的列顺序重新排列列
    ordered_columns = [col for col in desired_order if col in df.columns]

    output = io.StringIO()
    df.to_csv(output, index=False, columns=ordered_columns)
    output.seek(0)

    # Save the translated CSV to a file
    output_path = os.path.join(os.getcwd(), output_filename)
    with open(output_path, 'w') as f:
        f.write(output.getvalue())

    progress['filename'] = output_filename
    progress['finished'] = True
    print(f"Translation completed. File saved as {output_filename}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/translate', methods=['POST'])
def translate():
    global progress
    file = request.files['file']
    file_content = file.read().decode('utf-8')
    translation_target = request.form['translation_target']
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
    progress['finished'] = False

    translation_thread = threading.Thread(target=perform_translation, args=(file_content, languages, translation_target))
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