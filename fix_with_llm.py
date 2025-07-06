#!/usr/bin/env python3

import json
import os
import sys
import tempfile
import logging
import subprocess
import difflib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from openai import OpenAI
from tqdm import tqdm

# プロジェクトのルートディレクトリをPythonパスに追加するのだ
project_root = str(Path(__file__).parent.parent)
sys.path.append(project_root)

# 最大リトライ回数を設定するのだ
MAX_RETRY_ATTEMPTS = 5

# ロギングの設定をするのだ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('llm_fix_debug.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def create_temp_source(code: str, deps: str) -> str:
    """一時的なソースファイルを作成するのだ"""
    with tempfile.NamedTemporaryFile(suffix='.c', delete=False, mode='w') as f:
        f.write(deps)
        f.write('\n')
        f.write(code)
        return f.name

def compile_code(source_file: str) -> Tuple[bool, str]:
    """コードをコンパイルして結果を返すのだ"""
    try:
        result = subprocess.run(
            ['gcc', '-std=c11', '-O2', '-c', source_file],
            capture_output=True,
            text=True
        )
        return result.returncode == 0, result.stderr
    except Exception as e:
        return False, str(e)

def get_code_diff(original: str, modified: str) -> Dict[str, int]:
    """2つのコードの差分を計算するのだ"""
    diff = difflib.unified_diff(
        original.splitlines(),
        modified.splitlines(),
        lineterm=''
    )
    diff_lines = list(diff)
    
    # 追加・削除・変更された行数をカウントするのだ
    added = sum(1 for line in diff_lines if line.startswith('+') and not line.startswith('+++'))
    removed = sum(1 for line in diff_lines if line.startswith('-') and not line.startswith('---'))
    changed = min(added, removed)  # 変更された行は追加と削除の最小値として計算するのだ
    
    return {
        'added_lines': added,
        'removed_lines': removed,
        'changed_lines': changed,
        'total_changes': added + removed - changed  # 変更は1回としてカウントするのだ
    }

def fix_code_with_llm(code: str, error_msg: str, client: OpenAI, attempt: int = 1) -> Optional[str]:
    """LLMを使ってコードを修正するのだ"""
    try:
        # リトライ回数に応じてプロンプトを調整するのだ
        if attempt == 1:
            prompt = f"""以下のCコードを修正してください。コンパイルエラーを解消する必要があります。
エラーメッセージ:
{error_msg}

元のコード:
```c
{code}
```

修正後のコードのみを返してください。コードブロックは```cで始めてください。"""
        else:
            prompt = f"""以下のCコードを修正してください。既に{attempt-1}回修正を試みましたが、まだコンパイルエラーが残っています。
最新のエラーメッセージ:
{error_msg}

元のコード:
```c
{code}
```

前回の修正でもエラーが残っているため、より慎重に修正してください。コンパイルエラーを完全に解消する必要があります。

修正後のコードのみを返してください。コードブロックは```cで始めてください。"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",  
            messages=[
                {"role": "system", "content": "あなたはC言語のエキスパートです。コンパイルエラーを修正するのに特化しています。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1  # より決定論的な出力を得るために低めの温度を設定するのだ
        )
        
        # レスポンスからコードを抽出するのだ
        fixed_code = response.choices[0].message.content
        if "```c" in fixed_code:
            fixed_code = fixed_code.split("```c")[1].split("```")[0].strip()
        return fixed_code
    except Exception as e:
        logger.error(f"LLM API呼び出しでエラーが発生したのだ: {str(e)}")
        return None

def process_code_pair(pair: Dict, client: OpenAI) -> Dict:
    """1つのコードペアを処理するのだ"""
    # 一時ファイルを作成するのだ
    temp_file = create_temp_source(pair['decompiled_code'], pair['dep'])
    logger.info(f"Processing code pair with temp file: {temp_file}")
    
    try:
        # まず元のコードをコンパイルしてみるのだ
        success, error_msg = compile_code(temp_file)
        
        if success:
            logger.info("Code already compiles successfully!")
            return {
                'original_code': pair['original_code'],
				'base_decompiled_code': pair['decompiled_code'],
                'fixed_code': pair['decompiled_code'],
                'dep': pair.get('dep', ''),
                'success': True,
                'error_msg': None,
                'changes': {'added_lines': 0, 'removed_lines': 0, 'changed_lines': 0, 'total_changes': 0},
                'attempts': 0
            }
        
        # LLMで修正を繰り返し試みるのだ
        current_code = pair['decompiled_code']
        total_changes = {'added_lines': 0, 'removed_lines': 0, 'changed_lines': 0, 'total_changes': 0}
        attempts = 0
        
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            attempts = attempt
            logger.info(f"Attempt {attempt}/{MAX_RETRY_ATTEMPTS} to fix compilation error")
            
            # LLMで修正を試みるのだ
            fixed_code = fix_code_with_llm(current_code, error_msg, client, attempt)
            if not fixed_code:
                logger.warning(f"LLM failed to generate fixed code on attempt {attempt}")
                break
            
            # 修正されたコードをコンパイルしてみるのだ
            with open(temp_file, 'w') as f:
                f.write(pair['dep'])
                f.write('\n')
                f.write(fixed_code)
            
            success, new_error_msg = compile_code(temp_file)
            
            if success:
                logger.info(f"Compilation successful after {attempt} attempts!")
                # 累積的な変更量を計算するのだ
                cumulative_changes = get_code_diff(pair['decompiled_code'], fixed_code)
                return {
                    'original_code': pair['original_code'],
                    'base_decompiled_code': pair['decompiled_code'],
                    'fixed_code': fixed_code,
                    'dep': pair.get('dep', ''),
                    'success': True,
                    'error_msg': None,
                    'changes': cumulative_changes,
                    'attempts': attempt
                }
            else:
                logger.info(f"Attempt {attempt} failed, error: {new_error_msg.split(chr(10))[0]}")
                # 次の試行のために現在のコードとエラーメッセージを更新するのだ
                current_code = fixed_code
                error_msg = new_error_msg
        
        # 最大試行回数に達しても成功しなかった場合
        logger.warning(f"Failed to fix compilation error after {MAX_RETRY_ATTEMPTS} attempts")
        return {
            'original_code': pair['original_code'],
			'base_decompiled_code': pair['decompiled_code'],
            'fixed_code': current_code,  # 最後に試行したコードを保存するのだ
            'dep': pair.get('dep', ''),
            'success': False,
            'error_msg': error_msg,
            'changes': get_code_diff(pair['decompiled_code'], current_code),
            'attempts': attempts
        }
        
    except Exception as e:
        logger.error(f"Error while processing code pair: {str(e)}", exc_info=True)
        return {
            'original_code': pair['original_code'],
			'base_decompiled_code': pair['decompiled_code'],
            'fixed_code': None,
            'dep': pair.get('dep', ''),
            'success': False,
            'error_msg': str(e),
            'changes': None,
            'attempts': 0
        }
    finally:
        os.unlink(temp_file)

def main():
    if len(sys.argv) != 2:
        print("Usage: python fix_with_llm.py <openai_api_key>")
        sys.exit(1)
    
    api_key = sys.argv[1]
    client = OpenAI(api_key=api_key)
    logger.info("Starting to process failed compilation pairs with LLM...")
    opt = "o2"
    
    # 入力ファイルを読み込むのだ
    input_file = f'dataset/{opt}_failed_compilation_pairs.json'
    logger.info(f"Reading input file: {input_file}")
    with open(input_file, 'r') as f:
        code_pairs = json.load(f)
    
    logger.info(f"Found {len(code_pairs)} code pairs to process")
    
    # 各コードペアを修正するのだ
    fixed_pairs = []
    for pair in tqdm(code_pairs, desc="Processing pairs"):
        fixed_pair = process_code_pair(pair, client)
        fixed_pairs.append(fixed_pair)
    
    # 結果を保存するのだ
    output_file = f'dataset/{opt}_llm_fixed_pairs.json'
    logger.info(f"Saving results to: {output_file}")
    with open(output_file, 'w') as f:
        json.dump(fixed_pairs, f, indent=2)
    
    # 統計を表示するのだ
    success_count = sum(1 for pair in fixed_pairs if pair['success'])
    total_changes = [pair['changes']['total_changes'] for pair in fixed_pairs if pair['success'] and pair['changes']]
    attempt_counts = [pair['attempts'] for pair in fixed_pairs if pair['success']]
    
    logger.info("\n=== Results ===")
    logger.info(f"Total pairs: {len(fixed_pairs)}")
    logger.info(f"Successfully fixed: {success_count}")
    logger.info(f"Failed to fix: {len(fixed_pairs) - success_count}")
    logger.info(f"Success rate: {success_count/len(fixed_pairs)*100:.2f}%")
    
    if attempt_counts:
        logger.info("\n=== Attempt Statistics ===")
        logger.info(f"Average attempts per successful fix: {sum(attempt_counts)/len(attempt_counts):.2f}")
        logger.info(f"Min attempts: {min(attempt_counts)}")
        logger.info(f"Max attempts: {max(attempt_counts)}")
        
        # 試行回数別の成功数を表示するのだ
        attempt_distribution = {}
        for attempts in attempt_counts:
            attempt_distribution[attempts] = attempt_distribution.get(attempts, 0) + 1
        
        logger.info("Success distribution by attempts:")
        for attempts, count in sorted(attempt_distribution.items()):
            logger.info(f"  - {attempts} attempt(s): {count} cases")
    
    if total_changes:
        logger.info("\n=== Change Statistics ===")
        logger.info(f"Average changes per fix: {sum(total_changes)/len(total_changes):.2f}")
        logger.info(f"Min changes: {min(total_changes)}")
        logger.info(f"Max changes: {max(total_changes)}")
    
    # 失敗したケースのエラー統計を表示するのだ
    if len(fixed_pairs) - success_count > 0:
        logger.info("\n=== Error Statistics ===")
        error_counts = {}
        for pair in fixed_pairs:
            if not pair['success'] and pair['error_msg']:
                error_msg = pair['error_msg'].split('\n')[0]  # 最初のエラーメッセージのみを使用するのだ
                error_counts[error_msg] = error_counts.get(error_msg, 0) + 1
        
        logger.info("Most common errors:")
        for error, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            logger.info(f"  - {error}: {count} occurrences")

if __name__ == '__main__':
    main() 