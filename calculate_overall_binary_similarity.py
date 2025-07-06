#!/usr/bin/env python3
"""
LLMで修正されたものとそうでないものを合算した距離ベース類似度の統計を計算するスクリプト

使用方法:
    python calculate_overall_binary_similarity.py <opt>
    
例:
    python calculate_overall_binary_similarity.py o0
    python calculate_overall_binary_similarity.py o2
"""

import json
import sys
import statistics
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
from tqdm import tqdm

# プロジェクトのルートディレクトリをPythonパスに追加するのだ
project_root = str(Path(__file__).parent.parent)
sys.path.append(project_root)

# compare_binary_distance.pyから関数をインポートするのだ
from eval.compare_binary_distance import (
    normalize_disasm,
    extract_instructions,
    compute_similarity,
    calculate_statistics
)

def load_compiled_pairs(opt: str) -> List[Dict]:
    """コンパイル成功したペアを読み込むのだ"""
    file_path = f'dataset/{opt}_compiled_pairs.json'
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        print(f"Loaded {len(data)} compiled pairs from {file_path}")
        return data
    except FileNotFoundError:
        print(f"Warning: {file_path} not found")
        return []

def load_llm_fixed_pairs(opt: str) -> List[Dict]:
    """LLMで修正されたペアを読み込むのだ"""
    file_path = f'dataset/{opt}_llm_fixed_pairs.json'
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        print(f"Loaded {len(data)} LLM fixed pairs from {file_path}")
        return data
    except FileNotFoundError:
        print(f"Warning: {file_path} not found")
        return []

def load_llm_fixed_binary_compare(opt: str) -> List[Dict]:
    """LLMで修正されたバイナリ比較結果を読み込むのだ"""
    file_path = f'dataset/{opt}_llm_fixed_binary_compare.json'
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        print(f"Loaded {len(data['pairs'])} LLM fixed binary compare pairs from {file_path}")
        return data['pairs']
    except FileNotFoundError:
        print(f"Warning: {file_path} not found")
        return []

def calculate_binary_similarity_for_pair(pair: Dict) -> Tuple[float, int, int]:
    """1つのペアのバイナリ類似度を計算するのだ"""
    try:
        # アセンブリコードを正規化して命令列を抽出するのだ
        original_insns = extract_instructions(normalize_disasm(pair['original_asm']))
        fixed_insns = extract_instructions(normalize_disasm(pair['decompiled_asm']))
        
        # 類似度を計算するのだ
        similarity = compute_similarity(original_insns, fixed_insns)
        
        return similarity, len(original_insns), len(fixed_insns)
    except Exception as e:
        print(f"Error calculating similarity for pair: {e}")
        return 0.0, 0, 0

def process_compiled_pairs(compiled_pairs: List[Dict]) -> List[Dict]:
    """コンパイル成功したペアを処理してバイナリ類似度を計算するのだ"""
    results = []
    
    for pair in tqdm(compiled_pairs, desc="Processing compiled pairs"):
        try:
            # バイナリ類似度を計算するのだ
            similarity, original_count, fixed_count = calculate_binary_similarity_for_pair(pair)
            
            result = {
                'type': 'compiled',
                'original_code': pair['original_code'],
                'fixed_code': pair['decompiled_code'],
                'binary_similarity': similarity,
                'original_insn_count': original_count,
                'fixed_insn_count': fixed_count,
                'success': True
            }
            results.append(result)
            
        except Exception as e:
            print(f"Error processing compiled pair: {e}")
            continue
    
    return results

def process_llm_fixed_pairs(llm_fixed_pairs: List[Dict], llm_binary_compare: List[Dict]) -> List[Dict]:
    """LLMで修正されたペアを処理してバイナリ類似度を計算するのだ"""
    results = []
    
    # LLMバイナリ比較結果を辞書に変換するのだ（original_codeをキーとして）
    binary_compare_dict = {}
    for pair in llm_binary_compare:
        binary_compare_dict[pair['original_code']] = pair
    
    for pair in tqdm(llm_fixed_pairs, desc="Processing LLM fixed pairs"):
        try:
            # LLMバイナリ比較結果から類似度を取得するのだ
            if pair['original_code'] in binary_compare_dict:
                binary_pair = binary_compare_dict[pair['original_code']]
                similarity = binary_pair['binary_similarity']
                original_count = binary_pair['original_insn_count']
                fixed_count = binary_pair['fixed_insn_count']
            else:
                # バイナリ比較結果がない場合は計算するのだ
                similarity, original_count, fixed_count = calculate_binary_similarity_for_pair(pair)
            
            result = {
                'type': 'llm_fixed',
                'original_code': pair['original_code'],
                'fixed_code': pair['fixed_code'],
                'binary_similarity': similarity,
                'original_insn_count': original_count,
                'fixed_insn_count': fixed_count,
                'success': pair['success'],
                'attempts': pair.get('attempts', 0)
            }
            results.append(result)
            
        except Exception as e:
            print(f"Error processing LLM fixed pair: {e}")
            continue
    
    return results

def calculate_overall_statistics(all_pairs: List[Dict]) -> Dict:
    """全体の統計を計算するのだ"""
    # 類似度のリストを抽出するのだ
    similarities = [pair['binary_similarity'] for pair in all_pairs if pair['binary_similarity'] is not None]
    
    if not similarities:
        return {
            "mean": 0.0,
            "median": 0.0,
            "stdev": 0.0,
            "min": 0.0,
            "max": 0.0,
            "q1": 0.0,
            "q3": 0.0
        }
    
    return calculate_statistics(similarities)

def calculate_type_statistics(pairs: List[Dict], pair_type: str) -> Dict:
    """特定タイプのペアの統計を計算するのだ"""
    type_pairs = [pair for pair in pairs if pair['type'] == pair_type]
    similarities = [pair['binary_similarity'] for pair in type_pairs if pair['binary_similarity'] is not None]
    
    if not similarities:
        return {
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "stdev": 0.0,
            "min": 0.0,
            "max": 0.0,
            "q1": 0.0,
            "q3": 0.0
        }
    
    stats = calculate_statistics(similarities)
    stats["count"] = len(type_pairs)
    return stats

def main():
    parser = argparse.ArgumentParser(description='Calculate overall binary similarity statistics')
    parser.add_argument('opt', choices=['o0', 'o2'], help='Optimization level (o0 or o2)')
    args = parser.parse_args()
    
    opt = args.opt
    print(f"Processing optimization level: {opt}")
    
    # データを読み込むのだ
    compiled_pairs = load_compiled_pairs(opt)
    llm_fixed_pairs = load_llm_fixed_pairs(opt)
    llm_binary_compare = load_llm_fixed_binary_compare(opt)
    
    # 各タイプのペアを処理するのだ
    compiled_results = process_compiled_pairs(compiled_pairs)
    llm_fixed_results = process_llm_fixed_pairs(llm_fixed_pairs, llm_binary_compare)
    
    # 全体のペアを結合するのだ
    all_pairs = compiled_results + llm_fixed_results
    
    print(f"\nTotal pairs processed: {len(all_pairs)}")
    print(f"Compiled pairs: {len(compiled_results)}")
    print(f"LLM fixed pairs: {len(llm_fixed_results)}")
    
    # 統計を計算するのだ
    overall_stats = calculate_overall_statistics(all_pairs)
    compiled_stats = calculate_type_statistics(all_pairs, 'compiled')
    llm_fixed_stats = calculate_type_statistics(all_pairs, 'llm_fixed')
    
    # 結果を表示するのだ
    print("\n" + "="*60)
    print("OVERALL BINARY SIMILARITY STATISTICS")
    print("="*60)
    print(f"Total pairs: {len(all_pairs)}")
    print(f"Mean similarity: {overall_stats['mean']:.2f}%")
    print(f"Median: {overall_stats['median']:.2f}%")
    print(f"Standard deviation: {overall_stats['stdev']:.2f}%")
    print(f"Min: {overall_stats['min']:.2f}%")
    print(f"Max: {overall_stats['max']:.2f}%")
    print(f"Q1 (25th percentile): {overall_stats['q1']:.2f}%")
    print(f"Q3 (75th percentile): {overall_stats['q3']:.2f}%")
    
    print("\n" + "-"*40)
    print("COMPILED PAIRS STATISTICS")
    print("-"*40)
    print(f"Count: {compiled_stats['count']}")
    print(f"Mean similarity: {compiled_stats['mean']:.2f}%")
    print(f"Median: {compiled_stats['median']:.2f}%")
    print(f"Standard deviation: {compiled_stats['stdev']:.2f}%")
    print(f"Min: {compiled_stats['min']:.2f}%")
    print(f"Max: {compiled_stats['max']:.2f}%")
    
    print("\n" + "-"*40)
    print("LLM FIXED PAIRS STATISTICS")
    print("-"*40)
    print(f"Count: {llm_fixed_stats['count']}")
    print(f"Mean similarity: {llm_fixed_stats['mean']:.2f}%")
    print(f"Median: {llm_fixed_stats['median']:.2f}%")
    print(f"Standard deviation: {llm_fixed_stats['stdev']:.2f}%")
    print(f"Min: {llm_fixed_stats['min']:.2f}%")
    print(f"Max: {llm_fixed_stats['max']:.2f}%")
    
    # 類似度分布を表示するのだ
    similarities = [pair['binary_similarity'] for pair in all_pairs if pair['binary_similarity'] is not None]
    print("\n" + "-"*40)
    print("SIMILARITY DISTRIBUTION")
    print("-"*40)
    ranges = [(0.0, 20.0), (20.0, 40.0), (40.0, 60.0), (60.0, 80.0), (80.0, 100.0)]
    for start, end in ranges:
        count = sum(1 for s in similarities if start <= s < end)
        percentage = count / len(similarities) * 100 if similarities else 0
        print(f"{start:.1f}%-{end:.1f}%: {count} pairs ({percentage:.1f}%)")
    
    # 結果をファイルに保存するのだ
    output_file = f'dataset/{opt}_overall_binary_similarity_stats.json'
    result_data = {
        'optimization_level': opt,
        'total_pairs': len(all_pairs),
        'overall_statistics': overall_stats,
        'compiled_statistics': compiled_stats,
        'llm_fixed_statistics': llm_fixed_stats,
        'pairs': all_pairs
    }
    
    with open(output_file, 'w') as f:
        json.dump(result_data, f, indent=2)
    
    print(f"\nResults saved to: {output_file}")

if __name__ == '__main__':
    main() 