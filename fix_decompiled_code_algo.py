#!/usr/bin/env python3

import json
import os
import sys
import tempfile
import logging
from pathlib import Path
from typing import Optional, List


# プロジェクトのルートディレクトリをPythonパスに追加するのだ
project_root = str(Path(__file__).parent.parent)
sys.path.append(project_root)

from src.fix_compilation.core.fix_compilation import FixCompilation
import src.fix_compilation.fixers

# ロギングの設定をするのだ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fix_decompiled_debug.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def create_temp_source(code: str, deps: str) -> str:
    """一時的なソースファイルを作成するのだ"""
    with tempfile.NamedTemporaryFile(suffix='.c', delete=False, mode='w') as f:
        # 依存関係を先に書くのだ
        f.write(deps)
        f.write('\n')
        # メインのコードを書くのだ
        f.write(code)
        return f.name

def analyze_compiler_errors(compiler_output: str) -> List[str]:
    """コンパイラのエラー出力を解析して、エラーメッセージのリストを返すのだ"""
    errors = []
    for line in compiler_output.split('\n'):
        if 'error:' in line:
            # エラーメッセージの部分だけを抽出するのだ
            error_msg = line.split('error:')[-1].strip()
            if error_msg and error_msg not in errors:
                errors.append(error_msg)
    return errors

def fix_code_pair(code_pair: dict) -> dict:
    """1つのコードペアを修正するのだ"""
    temp_file = create_temp_source(code_pair['decompiled_code'], code_pair['dep'])
    logger.info(f"Processing code pair with temp file: {temp_file}")
    
    try:
        # コンパイルエラーを修正するのだ
        fixer = FixCompilation(
            source_path=temp_file,
            max_attempts=10,
            compiler_options=['-std=c11', '-O2'],  # O2最適化を指定するのだ
            use_clang_tidy=True
        )
        
        # コンパイルを試みるのだ
        success = fixer.run()
        
        # コンパイラの出力を取得するのだ
        compiler_output = fixer.last_compiler_output if hasattr(fixer, 'last_compiler_output') else ""
        errors = analyze_compiler_errors(compiler_output)
        
        if success:
            logger.info("Successfully fixed the code!")
            # 修正されたコードを読み込むのだ
            with open(temp_file, 'r') as f:
                fixed_code = f.read()
            return {
                'original_code': code_pair['original_code'],
                'decompiled_code': code_pair['decompiled_code'],
                'fixed_code': fixed_code,
                'success': True,
                'errors': errors,
                'compiler_output': compiler_output
            }
        else:
            logger.warning(f"Failed to fix the code. Found {len(errors)} errors:")
            for error in errors:
                logger.warning(f"  - {error}")
            return {
                'original_code': code_pair['original_code'],
                'decompiled_code': code_pair['decompiled_code'],
                'fixed_code': None,
                'success': False,
                'errors': errors,
                'compiler_output': compiler_output
            }
    except Exception as e:
        logger.error(f"Error while processing code pair: {str(e)}", exc_info=True)
        return {
            'original_code': code_pair['original_code'],
            'decompiled_code': code_pair['decompiled_code'],
            'fixed_code': None,
            'success': False,
            'errors': [str(e)],
            'compiler_output': ""
        }
    finally:
        # 一時ファイルを削除するのだ
        os.unlink(temp_file)
        logger.debug(f"Removed temporary file: {temp_file}")

def main():
    logger.info("Starting to process failed compilation pairs...")
    
    # 入力ファイルを読み込むのだ
    input_file = 'dataset/o2_failed_compilation_pairs.json'
    logger.info(f"Reading input file: {input_file}")
    with open(input_file, 'r') as f:
        code_pairs = json.load(f)
    
    logger.info(f"Found {len(code_pairs)} code pairs to process")
    
    # 各コードペアを修正するのだ
    fixed_pairs = []
    for i, pair in enumerate(code_pairs, 1):
        logger.info(f"Processing pair {i}/{len(code_pairs)}...")
        fixed_pair = fix_code_pair(pair)
        fixed_pairs.append(fixed_pair)
    
    # 結果を保存するのだ
    output_file = 'dataset/o2_fixed_decompiled_pairs.json'
    logger.info(f"Saving results to: {output_file}")
    with open(output_file, 'w') as f:
        json.dump(fixed_pairs, f, indent=2)
    
    # 統計を表示するのだ
    success_count = sum(1 for pair in fixed_pairs if pair['success'])
    logger.info("\n=== Results ===")
    logger.info(f"Total pairs: {len(fixed_pairs)}")
    logger.info(f"Successfully fixed: {success_count}")
    logger.info(f"Failed to fix: {len(fixed_pairs) - success_count}")
    
    # 失敗したケースのエラー統計を表示するのだ
    if len(fixed_pairs) - success_count > 0:
        logger.info("\n=== Error Statistics ===")
        error_counts = {}
        for pair in fixed_pairs:
            if not pair['success']:
                for error in pair['errors']:
                    error_counts[error] = error_counts.get(error, 0) + 1
        
        logger.info("Most common errors:")
        for error, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            logger.info(f"  - {error}: {count} occurrences")

if __name__ == '__main__':
    main() 