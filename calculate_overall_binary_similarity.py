#!/usr/bin/env python3
"""
Script to calculate distance-based similarity statistics combining LLM-fixed and non-fixed data

Usage:
    python calculate_overall_binary_similarity.py <opt>
    
Examples:
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

# Add project root directory to Python path
project_root = str(Path(__file__).parent.parent)
sys.path.append(project_root)

# Import functions from compare_binary_distance.py
from eval.compare_binary_distance import (
    normalize_disasm,
    extract_instructions,
    compute_similarity,
    calculate_statistics
)

def load_compiled_pairs(opt: str) -> List[Dict]:
    """Load successfully compiled pairs"""
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
    """Load LLM-fixed pairs"""
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
    """Load LLM-fixed binary comparison results"""
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
    """Calculate binary similarity for a single pair"""
    try:
        # Normalize assembly code and extract instruction sequences
        original_insns = extract_instructions(normalize_disasm(pair['original_asm']))
        fixed_insns = extract_instructions(normalize_disasm(pair['decompiled_asm']))
        
        # Calculate similarity
        similarity = compute_similarity(original_insns, fixed_insns)
        
        return similarity, len(original_insns), len(fixed_insns)
    except Exception as e:
        print(f"Error calculating similarity for pair: {e}")
        return 0.0, 0, 0

def process_compiled_pairs(compiled_pairs: List[Dict]) -> List[Dict]:
    """Process successfully compiled pairs and calculate binary similarity"""
    results = []
    
    for pair in tqdm(compiled_pairs, desc="Processing compiled pairs"):
        try:
            # Calculate binary similarity
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
    """Process LLM-fixed pairs and calculate binary similarity"""
    results = []
    
    # Convert LLM binary comparison results to dictionary (using original_code as key)
    binary_compare_dict = {}
    for pair in llm_binary_compare:
        binary_compare_dict[pair['original_code']] = pair
    
    for pair in tqdm(llm_fixed_pairs, desc="Processing LLM fixed pairs"):
        try:
            # Get similarity from LLM binary comparison results
            if pair['original_code'] in binary_compare_dict:
                binary_pair = binary_compare_dict[pair['original_code']]
                similarity = binary_pair['binary_similarity']
                original_count = binary_pair['original_insn_count']
                fixed_count = binary_pair['fixed_insn_count']
            else:
                # Calculate if no binary comparison result exists
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
    """Calculate overall statistics"""
    # Extract similarity list
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
    """Calculate statistics for specific type of pairs"""
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
    
    # Load data
    compiled_pairs = load_compiled_pairs(opt)
    llm_fixed_pairs = load_llm_fixed_pairs(opt)
    llm_binary_compare = load_llm_fixed_binary_compare(opt)
    
    # Process each type of pairs
    compiled_results = process_compiled_pairs(compiled_pairs)
    llm_fixed_results = process_llm_fixed_pairs(llm_fixed_pairs, llm_binary_compare)
    
    # Combine all pairs
    all_pairs = compiled_results + llm_fixed_results
    
    print(f"\nTotal pairs processed: {len(all_pairs)}")
    print(f"Compiled pairs: {len(compiled_results)}")
    print(f"LLM fixed pairs: {len(llm_fixed_results)}")
    
    # Calculate statistics
    overall_stats = calculate_overall_statistics(all_pairs)
    compiled_stats = calculate_type_statistics(all_pairs, 'compiled')
    llm_fixed_stats = calculate_type_statistics(all_pairs, 'llm_fixed')
    
    # Display results
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
    
    # Display similarity distribution
    similarities = [pair['binary_similarity'] for pair in all_pairs if pair['binary_similarity'] is not None]
    print("\n" + "-"*40)
    print("SIMILARITY DISTRIBUTION")
    print("-"*40)
    ranges = [(0.0, 20.0), (20.0, 40.0), (40.0, 60.0), (60.0, 80.0), (80.0, 100.0)]
    for start, end in ranges:
        count = sum(1 for s in similarities if start <= s < end)
        percentage = count / len(similarities) * 100 if similarities else 0
        print(f"{start:.1f}%-{end:.1f}%: {count} pairs ({percentage:.1f}%)")
    
    # Save results to file
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