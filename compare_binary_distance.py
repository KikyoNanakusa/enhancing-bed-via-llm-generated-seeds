#!/usr/bin/env python3
"""
Script to calculate binary similarity (instruction-level matching rate)

Usage:
    1. For both target and candidate binaries, execute:
       $ objdump -d <binary> > <output_file>
       to save the disassembly results to files.
    2. Pass the target and candidate objdump text files as arguments to this script:
       $ chmod +x bin_match.py
       $ ./bin_match.py target.dump candidate.dump
    3. The instruction-level matching rate (%) will be displayed as command output.

    Or, for processing JSON files:
    $ python3 compare_binary_distance.py input.json output.json

Algorithm overview:
    1. Load objdump -d output
    2. Remove padding instructions (NOPs, etc.) and normalize jump/call addresses
    3. Extract only assembly instruction parts line by line into a list
    4. Calculate edit distance (d) using SequenceMatcher
    5. Calculate and output matching rate = (N - d) / N * 100
"""

import re
import sys
import json
import statistics
from pathlib import Path
from typing import List, Dict, Any, Tuple
from difflib import SequenceMatcher
from tqdm import tqdm


def load_objdump(filepath: str) -> str:
    """
    Load objdump -d output text
    (Specify file path, or pass '-' to read from standard input)
    """
    if filepath == '-':
        return sys.stdin.read()
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def normalize_disasm(text: str) -> str:
    """
    Normalize disassembly text:
      1. Remove padding instructions (NOPs, etc.)
      2. Replace address operands of branch instructions (call/jmp/je/jne, etc.) with "SEC+OFFSET"
      3. Remove unnecessary hexadecimal byte sequences and trim extra whitespace

    Normalization method source: Schulte et al. 2018 §III-B1
        "We remove irrelevant nop and other padding instructions meant to align code ...
         We identify instructions that change the program counter, such as jmp 0x8014040
         or call 0x8014080 and replace the address operand with the function name or ELF
         section name and offset..."
    """
    lines = []
    for line in text.splitlines():
        # Disassembly line format example:
        #   401000:   55                      push   %rbp
        #   401001:   48 89 e5                mov    %rsp,%rbp
        # Extract "address: byte_sequence instruction" format using regex
        m = re.match(r'^\s*[0-9A-Fa-f]+:\s+([0-9A-Fa-f ]+)\s+(.+)$', line)
        if not m:
            continue

        byte_seq = m.group(1).strip()   # Example: "55" or "48 89 e5"
        asm_insn = m.group(2).strip()  # Example: "push   %rbp"

        # 1) Remove padding instructions (nop, pause, etc.)
        #    Paper explicitly mentions removing "irrelevant nop and other padding instructions"
        #    Example: Check exact match for "nop" or "pause"
        if asm_insn.startswith('nop') or asm_insn.startswith('pause'):
            continue  # Exclude

        # 2) Replace address operands of jump/call instructions
        #    Example: "jmp 0x400510" -> "jmp <TARGET>"
        #    Replacement pattern: \b(call|jmp|je|jne|jg|jl|jle|jge)\s+0x[0-9A-Fa-f]+
        asm_insn = re.sub(
            r'\b(call|jmp|je|jne|jz|jnz|jg|jge|jl|jle)\s+0x[0-9A-Fa-f]+',
            r'\1 <ADDR>',
            asm_insn
        )

        # 3) Generalize other absolute addresses or immediate values (0x1234 or 1234) to <IMM>
        #    This also eliminates non-address context differences
        asm_insn = re.sub(r'0x[0-9A-Fa-f]+|\b\d+\b', '<IMM>', asm_insn)

        # 4) Collapse consecutive whitespace to single space and trim
        asm_insn = re.sub(r'\s+', ' ', asm_insn).strip()

        lines.append(asm_insn)

    # Return normalized assembly instructions separated by newlines
    #   Example: ["push %rbp", "mov %rsp, %rbp", "call <ADDR>", ...]
    return '\n'.join(lines)


def extract_instructions(norm_text: str) -> list[str]:
    """
    Extract only instruction parts line by line from normalized disassembly text and convert to list.
    Each line is already in the state of "instruction string only", so use lines as list elements as-is.
    """
    # Return ignoring empty lines
    return [line for line in norm_text.splitlines() if line.strip()]


def compute_similarity(insnsA: list[str], insnsB: list[str]) -> float:
    """
    Calculate match rate based on longest common subsequence for instruction sequences (insnsA, insnsB)
    using SequenceMatcher and return as 0-100 percentage.

    - Uses Python standard library difflib.SequenceMatcher
    - Converts ratio() * 100 to percentage
    """
    sm = SequenceMatcher(None, insnsA, insnsB)
    return sm.ratio() * 100.0


def calculate_statistics(similarities: List[float]) -> Dict[str, float]:
    """Calculate statistics from list of similarities"""
    return {
        "mean": statistics.mean(similarities),
        "median": statistics.median(similarities),
        "stdev": statistics.stdev(similarities) if len(similarities) > 1 else 0.0,
        "min": min(similarities),
        "max": max(similarities),
        "q1": statistics.quantiles(similarities, n=4)[0],
        "q3": statistics.quantiles(similarities, n=4)[2]
    }


def process_json_file(input_path: Path, output_path: Path) -> None:
    """Load JSON file, calculate similarity for each pair, and save results"""
    try:
        with open(input_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error: Failed to load JSON file: {e}")
        return

    similarities = []
    for item in tqdm(data, desc="Comparing binary pairs"):
        try:
            # Normalize assembly code and extract instruction sequences
            decompiled_insns = extract_instructions(normalize_disasm(item["decompiled_asm"]))
            original_insns = extract_instructions(normalize_disasm(item["original_asm"]))

            # Calculate similarity
            sim = compute_similarity(decompiled_insns, original_insns)
            similarities.append(sim)

            # Add results to JSON
            item["binary_similarity_distance"] = sim
            item["decompiled_insn_count"] = len(decompiled_insns)
            item["original_insn_count"] = len(original_insns)
        except Exception as e:
            print(f"Error processing pair: {e}")
            item["binary_similarity_distance"] = None
            item["decompiled_insn_count"] = None
            item["original_insn_count"] = None

    # Calculate statistics
    stats = calculate_statistics(similarities)

    # Save results
    with open(output_path, "w") as f:
        json.dump({
            "pairs": data,
            "statistics": stats
        }, f, indent=2)

    # Display statistics
    print("\nBinary Similarity Statistics (Distance-based):")
    print(f"Mean: {stats['mean']:.2f}%")
    print(f"Median: {stats['median']:.2f}%")
    print(f"Standard Deviation: {stats['stdev']:.2f}%")
    print(f"Min: {stats['min']:.2f}%")
    print(f"Max: {stats['max']:.2f}%")
    print(f"Q1 (25th percentile): {stats['q1']:.2f}%")
    print(f"Q3 (75th percentile): {stats['q3']:.2f}%")
    print(f"\nTotal pairs processed: {len(data)}")
    print(f"Results saved to: {output_path}")


def process_single_pair(fileA: str, fileB: str):
    """Calculate and display similarity for a single pair (legacy functionality)"""
    # 1) Load objdump output
    rawA = load_objdump(fileA)  # Target binary disassembly result
    rawB = load_objdump(fileB)  # Candidate binary disassembly result

    # 2) Normalization process
    normA = normalize_disasm(rawA)  # Target's normalized disassembly
    normB = normalize_disasm(rawB)  # Candidate's normalized disassembly

    # 3) Extract instruction sequences
    insnsA = extract_instructions(normA)  # Example: ["push %rbp", "mov %rsp, %rbp", ...]
    insnsB = extract_instructions(normB)

    # Error if no instructions exist in target
    if len(insnsA) == 0:
        print("Error: Target instructions not found after normalization.", file=sys.stderr)
        sys.exit(1)

    # 4) Calculate match rate based on edit distance
    similarity = compute_similarity(insnsA, insnsB)
    # 5) Display results
    print(f"Instruction-level match rate: {similarity:.2f}% "
          f"(Target instruction count: {len(insnsA)}, Candidate instruction count: {len(insnsB)})")


def main():
    if len(sys.argv) == 3:
        if sys.argv[1].endswith('.json'):
            # JSON file processing mode
            input_path = Path(sys.argv[1])
            output_path = Path(sys.argv[2])
            process_json_file(input_path, output_path)
        else:
            # Single pair processing mode (legacy functionality)
            process_single_pair(sys.argv[1], sys.argv[2])
    else:
        print(f"Usage: {sys.argv[0]} <input_json> <output_json>", file=sys.stderr)
        print(f"   or: {sys.argv[0]} <target_objdump.txt> <candidate_objdump.txt>", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
