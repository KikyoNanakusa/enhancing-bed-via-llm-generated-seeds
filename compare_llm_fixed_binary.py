#!/usr/bin/env python3

import json
import os
import sys
import tempfile
import subprocess
import logging
import statistics
from pathlib import Path
from typing import Dict, List, Tuple, Optional
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('llm_binary_compare.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Define common header files
COMMON_HEADERS = """
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdbool.h>
#include <stdint.h>
#include <math.h>
"""

def create_temp_source(code: str, deps: str, suffix: str = '') -> str:
    """Create a temporary source file with the given code and dependencies."""
    with tempfile.NamedTemporaryFile(suffix=f'{suffix}.c', delete=False, mode='w') as f:
        # Add common header files
        f.write(COMMON_HEADERS)
        f.write('\n')
        # Add dependency header files
        if deps:
            f.write(deps)
            f.write('\n')
        # Add main code
        f.write(code)
        return f.name

def compile_code(source_file: str, output_file: str, opt: str) -> Tuple[bool, str, str]:
    """Compile the code and return the result."""
    try:
        # Execute compilation command
        result = subprocess.run(
            ['gcc', '-std=c11', f'-{opt}', '-c', source_file, '-o', output_file],
            capture_output=True,
            text=True
        )
        # Return compilation result
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def get_objdump_output(obj_file: str) -> Optional[str]:
    """Get the objdump output for the object file."""
    try:
        result = subprocess.run(
            ['objdump', '-d', obj_file],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception as e:
        logger.error(f"Error during objdump execution: {str(e)}")
        return None

def process_code_pair(pair: Dict, opt: str) -> Optional[Dict]:
    """Process a single code pair."""
    try:
        # Get dependencies
        deps = pair.get('dep', '')
        opt = opt.upper()
        
        # Create temporary files
        original_file = create_temp_source(pair['original_code'], deps, '_original')
        fixed_file = create_temp_source(pair['fixed_code'], deps, '_fixed')
        
        # Set object file paths
        original_obj = original_file + '.o'
        fixed_obj = fixed_file + '.o'
        
        # Compile both versions
        original_success, original_out, original_error = compile_code(original_file, original_obj, opt)
        fixed_success, fixed_out, fixed_error = compile_code(fixed_file, fixed_obj, opt)
        
        if not original_success:
            logger.warning(f"Original code compilation failed:")
            logger.warning(f"Error: {original_error}")
            logger.warning(f"Code:\n{pair['original_code']}")
            logger.warning(f"Dependencies:\n{deps}")
            return None
            
        if not fixed_success:
            logger.warning(f"Fixed code compilation failed:")
            logger.warning(f"Error: {fixed_error}")
            logger.warning(f"Code:\n{pair['fixed_code']}")
            logger.warning(f"Dependencies:\n{deps}")
            return None
        
        # Get objdump output
        original_asm = get_objdump_output(original_obj)
        fixed_asm = get_objdump_output(fixed_obj)
        
        if not original_asm or not fixed_asm:
            logger.warning("Failed to execute objdump")
            return None
        
        # Normalize assembly code and extract instructions
        original_norm = normalize_disasm(original_asm)
        fixed_norm = normalize_disasm(fixed_asm)
        
        original_insns = extract_instructions(original_norm)
        fixed_insns = extract_instructions(fixed_norm)
        
        # Calculate similarity
        similarity = compute_similarity(original_insns, fixed_insns)
        
        return {
            'original_code': pair['original_code'],
            'fixed_code': pair['fixed_code'],
            'dep': deps,
            'binary_similarity': similarity,
            'original_asm': original_asm,
            'fixed_asm': fixed_asm,
            'original_insn_count': len(original_insns),
            'fixed_insn_count': len(fixed_insns),
            'original_compile_output': original_out,
            'fixed_compile_output': fixed_out,
            'compile_success': True
        }
        
    except Exception as e:
        logger.error(f"Error processing code pair: {str(e)}", exc_info=True)
        return None
    finally:
        # Clean up temporary files
        for f in [original_file, fixed_file, original_obj, fixed_obj]:
            try:
                if os.path.exists(f):
                    os.unlink(f)
            except Exception as e:
                logger.warning(f"Failed to delete temporary file: {f} - {str(e)}")

def calculate_statistics(similarities: List[float]) -> Dict[str, float]:
    """Calculate statistics for the similarity scores."""
    if len(similarities) < 2:
        logger.warning("Insufficient data points for statistical analysis")
        return {
            "mean": similarities[0] if similarities else 0.0,
            "median": similarities[0] if similarities else 0.0,
            "stdev": 0.0,
            "min": similarities[0] if similarities else 0.0,
            "max": similarities[0] if similarities else 0.0,
            "q1": similarities[0] if similarities else 0.0,
            "q3": similarities[0] if similarities else 0.0
        }
    
    return {
        "mean": statistics.mean(similarities),
        "median": statistics.median(similarities),
        "stdev": statistics.stdev(similarities) if len(similarities) > 1 else 0.0,
        "min": min(similarities),
        "max": max(similarities),
        "q1": statistics.quantiles(similarities, n=4)[0],
        "q3": statistics.quantiles(similarities, n=4)[2]
    }

def main():
    # Read input file
    opt = "o2"
    input_file = f'dataset/{opt}_llm_fixed_pairs.json'
    logger.info(f"Reading input file: {input_file}")
    
    with open(input_file, 'r') as f:
        code_pairs = json.load(f)
    
    logger.info(f"Processing {len(code_pairs)} code pairs")
    
    # Process each code pair
    results = []
    success_count = 0
    compile_failures = 0
    
    for pair in tqdm(code_pairs, desc="Processing code pairs"):
        result = process_code_pair(pair, opt)
        if result:
            results.append(result)
            success_count += 1
        else:
            compile_failures += 1
    
    # Calculate statistics
    if results:
        similarities = [r['binary_similarity'] for r in results]
        stats = calculate_statistics(similarities)
        
        # Save results
        output_file = f'dataset/{opt}_llm_fixed_binary_compare.json'
        logger.info(f"Saving results to: {output_file}")
        
        with open(output_file, 'w') as f:
            json.dump({
                'pairs': results,
                'statistics': stats,
                'summary': {
                    'total_pairs': len(code_pairs),
                    'successful_pairs': success_count,
                    'compile_failures': compile_failures,
                    'success_rate': success_count / len(code_pairs) * 100 if code_pairs else 0.0
                }
            }, f, indent=2)
        
        # Display statistics
        logger.info("\n=== Binary Similarity Statistics ===")
        logger.info(f"Processed pairs: {len(results)}")
        logger.info(f"Compilation failures: {compile_failures}")
        logger.info(f"Success rate: {success_count/len(code_pairs)*100:.1f}%")
        
        if len(similarities) >= 2:
            logger.info(f"Mean similarity: {stats['mean']:.2f}%")
            logger.info(f"Median: {stats['median']:.2f}%")
            logger.info(f"Standard deviation: {stats['stdev']:.2f}%")
            logger.info(f"Minimum: {stats['min']:.2f}%")
            logger.info(f"Maximum: {stats['max']:.2f}%")
            logger.info(f"First quartile: {stats['q1']:.2f}%")
            logger.info(f"Third quartile: {stats['q3']:.2f}%")
            
            # Display similarity distribution
            logger.info("\n=== Similarity Distribution ===")
            ranges = [(0.0, 20.0), (20.0, 40.0), (40.0, 60.0), (60.0, 80.0), (80.0, 100.0)]
            for start, end in ranges:
                count = sum(1 for s in similarities if start <= s < end)
                logger.info(f"{start:.1f}%-{end:.1f}%: {count} pairs ({count/len(similarities):.1%})")
        else:
            logger.warning("At least 2 data points are required for statistical analysis")
            if similarities:
                logger.info(f"Similarity: {similarities[0]:.2f}%")
    else:
        logger.error("No successful pairs found")
        # Save empty results
        output_file = f'dataset/{opt}_llm_fixed_binary_compare.json'
        with open(output_file, 'w') as f:
            json.dump({
                'pairs': [],
                'statistics': calculate_statistics([]),
                'summary': {
                    'total_pairs': len(code_pairs),
                    'successful_pairs': 0,
                    'compile_failures': compile_failures,
                    'success_rate': 0.0
                }
            }, f, indent=2)

if __name__ == '__main__':
    main() 