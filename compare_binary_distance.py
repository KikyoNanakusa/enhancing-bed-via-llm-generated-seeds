#!/usr/bin/env python3
"""
バイナリ一致度（命令レベル一致率）を計算するスクリプト

使用方法:
    1. ターゲットバイナリと候補バイナリの双方に対して
       $ objdump -d <バイナリ> > <出力ファイル>
       を実行して逆アセンブル結果をファイルに保存する。
    2. 本スクリプトに対して、ターゲットの objdump テキストと
       候補の objdump テキストのファイルを引数として渡す。
       $ chmod +x bin_match.py
       $ ./bin_match.py target.dump candidate.dump
    3. コマンド出力として、命令レベル一致率(%) が表示される。

    または、JSONファイルを処理する場合:
    $ python3 compare_binary_distance.py input.json output.json

アルゴリズム概要:
    1. objdump -d の出力を読み込み
    2. パディング命令(NOP 等)を除去し、ジャンプ・コールのアドレスを正規化
    3. アセンブリ命令部分のみを行単位で抽出してリスト化
    4. SequenceMatcher を用いた編集距離 (d) の算出
    5. 一致率 = (N - d) / N * 100 を計算して出力
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
    objdump -d の出力テキストを読み込む
    （ファイルパスを指定、'-' を渡すと標準入力から読み込む）
    """
    if filepath == '-':
        return sys.stdin.read()
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def normalize_disasm(text: str) -> str:
    """
    逆アセンブルテキストを正規化する:
      1. パディング命令(NOPなど)を除去
      2. 分岐(call/jmp/je/jne など)命令のアドレスオペランドを "SEC+OFFSET" に置換
      3. 不要な16進数バイト列を除去し、余分な空白を詰める

    正規化手法の出典: Schulte et al. 2018 §III-B1
        "We remove irrelevant nop and other padding instructions meant to align code ...
         We identify instructions that change the program counter, such as jmp 0x8014040
         or call 0x8014080 and replace the address operand with the function name or ELF
         section name and offset..."
    """
    lines = []
    for line in text.splitlines():
        # 逆アセンブル行のフォーマット例:
        #   401000:   55                      push   %rbp
        #   401001:   48 89 e5                mov    %rsp,%rbp
        # 正規表現で「アドレス: バイト列 命令」という形式を抽出
        m = re.match(r'^\s*[0-9A-Fa-f]+:\s+([0-9A-Fa-f ]+)\s+(.+)$', line)
        if not m:
            continue

        byte_seq = m.group(1).strip()   # 例: "55" や "48 89 e5"
        asm_insn = m.group(2).strip()  # 例: "push   %rbp"

        # 1) パディング命令 (nop, paused など) を除去
        #    論文では「irrelevant nop and other padding instructions」を除去と明示
        #    例: "nop" や "pause" を完全一致チェック
        if asm_insn.startswith('nop') or asm_insn.startswith('pause'):
            continue  # 除外

        # 2) ジャンプ/コール命令のアドレスオペランドを置換
        #    例: "jmp 0x400510" -> "jmp <TARGET>"
        #    置換パターン: \b(call|jmp|je|jne|jg|jl|jle|jge)\s+0x[0-9A-Fa-f]+
        asm_insn = re.sub(
            r'\b(call|jmp|je|jne|jz|jnz|jg|jge|jl|jle)\s+0x[0-9A-Fa-f]+',
            r'\1 <ADDR>',
            asm_insn
        )

        # 3) 他の絶対アドレスや即値 (0x1234 や 1234) を <IMM> に一般化
        #    これにより、アドレス以外のコンテキスト差異も排除
        asm_insn = re.sub(r'0x[0-9A-Fa-f]+|\b\d+\b', '<IMM>', asm_insn)

        # 4) 連続する空白を単一スペースにしてトリム
        asm_insn = re.sub(r'\s+', ' ', asm_insn).strip()

        lines.append(asm_insn)

    # 正規化済みアセンブリ命令を改行区切りで返却
    #   例: ["push %rbp", "mov %rsp, %rbp", "call <ADDR>", ...]
    return '\n'.join(lines)


def extract_instructions(norm_text: str) -> list[str]:
    """
    正規化された逆アセンブルテキストから命令部分だけを行単位で抽出してリスト化する。
    各行は既に「命令文字列のみ」の状態になっているので、行そのままをリスト要素とする。
    """
    # 空行は無視して返却
    return [line for line in norm_text.splitlines() if line.strip()]


def compute_similarity(insnsA: list[str], insnsB: list[str]) -> float:
    """
    命令シーケンス (insnsA, insnsB) に対し、SequenceMatcher を用いて
    最長一致部分列に基づく一致率を計算し、0～100 のパーセンテージで返す。

    - Python 標準ライブラリ difflib.SequenceMatcher を使用
    - ratio() * 100 で百分率に変換
    """
    sm = SequenceMatcher(None, insnsA, insnsB)
    return sm.ratio() * 100.0


def calculate_statistics(similarities: List[float]) -> Dict[str, float]:
    """類似度のリストから統計量を計算する"""
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
    """JSONファイルを読み込み、各ペアの類似度を計算して保存する"""
    try:
        with open(input_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error: Failed to load JSON file: {e}")
        return

    similarities = []
    for item in tqdm(data, desc="Comparing binary pairs"):
        try:
            # アセンブリコードを正規化して命令列を抽出
            decompiled_insns = extract_instructions(normalize_disasm(item["decompiled_asm"]))
            original_insns = extract_instructions(normalize_disasm(item["original_asm"]))

            # 類似度を計算
            sim = compute_similarity(decompiled_insns, original_insns)
            similarities.append(sim)

            # 結果をJSONに追記
            item["binary_similarity_distance"] = sim
            item["decompiled_insn_count"] = len(decompiled_insns)
            item["original_insn_count"] = len(original_insns)
        except Exception as e:
            print(f"Error processing pair: {e}")
            item["binary_similarity_distance"] = None
            item["decompiled_insn_count"] = None
            item["original_insn_count"] = None

    # 統計情報を計算
    stats = calculate_statistics(similarities)

    # 結果を保存
    with open(output_path, "w") as f:
        json.dump({
            "pairs": data,
            "statistics": stats
        }, f, indent=2)

    # 統計情報を表示
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
    """単一のペアの類似度を計算して表示する（従来の機能）"""
    # 1) objdump 出力の読み込み
    rawA = load_objdump(fileA)  # ターゲットバイナリの逆アセンブル結果
    rawB = load_objdump(fileB)  # 候補バイナリの逆アセンブル結果

    # 2) 正規化処理
    normA = normalize_disasm(rawA)  # ターゲットの正規化済み逆アセンブル
    normB = normalize_disasm(rawB)  # 候補の正規化済み逆アセンブル

    # 3) 命令列の抽出
    insnsA = extract_instructions(normA)  # 例: ["push %rbp", "mov %rsp, %rbp", ...]
    insnsB = extract_instructions(normB)

    # もしターゲットに命令が存在しない場合はエラー
    if len(insnsA) == 0:
        print("Error: Target instructions not found after normalization.", file=sys.stderr)
        sys.exit(1)

    # 4) 編集距離に基づく一致率計算
    similarity = compute_similarity(insnsA, insnsB)
    # 5) 結果を表示
    print(f"命令レベル一致率: {similarity:.2f}% "
          f"(ターゲット命令数: {len(insnsA)}, 候補命令数: {len(insnsB)})")


def main():
    if len(sys.argv) == 3:
        # JSONファイルを処理するモード
        input_path = Path(sys.argv[1])
        output_path = Path(sys.argv[2])
        process_json_file(input_path, output_path)
    elif len(sys.argv) == 3 and not sys.argv[1].endswith('.json'):
        # 単一ペアを処理するモード（従来の機能）
        process_single_pair(sys.argv[1], sys.argv[2])
    else:
        print(f"Usage: {sys.argv[0]} <input_json> <output_json>", file=sys.stderr)
        print(f"   or: {sys.argv[0]} <target_objdump.txt> <candidate_objdump.txt>", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
