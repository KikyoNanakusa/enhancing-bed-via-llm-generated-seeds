import re
import sys
import json
import statistics
from pathlib import Path
from typing import List, Dict, Any, Tuple
from difflib import SequenceMatcher
from tqdm import tqdm


def extract_insns(objdump_text: str, normalize_imm: bool = True) -> List[str]:
    """
    objdump -d の出力から、命令部分だけを取り出し、
    オプションでアドレスや数値オペランドを正規化して返す。

    Args:
        objdump_text: objdump -d の出力テキスト
        normalize_imm: Trueの場合、数値を<IMM>に正規化。Falseの場合、生のアセンブリをそのまま使用
    """
    insns = []
    # 各行:  00400530: 55                    push   %rbp
    for line in objdump_text.splitlines():
        m = re.match(r"^\s*[0-9a-fA-F]+:\s+([0-9a-fA-F ]+)\s+([a-z]+\b.*)$", line)
        if not m:
            continue
        asm = m.group(2)
        if normalize_imm:
            # アドレスや即値を一般化: 数字／16進数リテラルを '<IMM>' に置換
            asm = re.sub(r"0x[0-9a-fA-F]+|\b\d+\b", "<IMM>", asm)
        # 複数スペースは一つに
        asm = re.sub(r"\s+", " ", asm).strip()
        insns.append(asm)
    return insns


def similarity(a: List[str], b: List[str]) -> float:
    """
    SequenceMatcher を使って、2 つの命令列の一致率を計算。
    ratio() が 0～1 の浮動小数なので、百分率にして返す。
    """
    sm = SequenceMatcher(None, a, b)
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

    similarities_normalized = []
    similarities_raw = []
    for item in tqdm(data, desc="Comparing binary pairs"):
        try:
            # 正規化した命令列と生の命令列を抽出
            decompiled_insns_norm = extract_insns(item["decompiled_asm"], normalize_imm=True)
            original_insns_norm = extract_insns(item["original_asm"], normalize_imm=True)
            decompiled_insns_raw = extract_insns(item["decompiled_asm"], normalize_imm=False)
            original_insns_raw = extract_insns(item["original_asm"], normalize_imm=False)

            # 両方のモードで類似度を計算
            sim_norm = similarity(decompiled_insns_norm, original_insns_norm)
            sim_raw = similarity(decompiled_insns_raw, original_insns_raw)
            similarities_normalized.append(sim_norm)
            similarities_raw.append(sim_raw)

            # 結果をJSONに追記
            item["binary_similarity_normalized"] = sim_norm
            item["binary_similarity_raw"] = sim_raw
            item["decompiled_insn_count"] = len(decompiled_insns_norm)
            item["original_insn_count"] = len(original_insns_norm)
        except Exception as e:
            print(f"Error processing pair: {e}")
            item["binary_similarity_normalized"] = None
            item["binary_similarity_raw"] = None
            item["decompiled_insn_count"] = None
            item["original_insn_count"] = None

    # 両方のモードで統計情報を計算
    stats_normalized = calculate_statistics(similarities_normalized)
    stats_raw = calculate_statistics(similarities_raw)

    # 結果を保存
    with open(output_path, "w") as f:
        json.dump({
            "pairs": data,
            "statistics": {
                "normalized": stats_normalized,
                "raw": stats_raw
            }
        }, f, indent=2)

    # 統計情報を表示
    print("\nBinary Similarity Statistics (Normalized):")
    print(f"Mean: {stats_normalized['mean']:.2f}%")
    print(f"Median: {stats_normalized['median']:.2f}%")
    print(f"Standard Deviation: {stats_normalized['stdev']:.2f}%")
    print(f"Min: {stats_normalized['min']:.2f}%")
    print(f"Max: {stats_normalized['max']:.2f}%")
    print(f"Q1 (25th percentile): {stats_normalized['q1']:.2f}%")
    print(f"Q3 (75th percentile): {stats_normalized['q3']:.2f}%")

    print("\nBinary Similarity Statistics (Raw):")
    print(f"Mean: {stats_raw['mean']:.2f}%")
    print(f"Median: {stats_raw['median']:.2f}%")
    print(f"Standard Deviation: {stats_raw['stdev']:.2f}%")
    print(f"Min: {stats_raw['min']:.2f}%")
    print(f"Max: {stats_raw['max']:.2f}%")
    print(f"Q1 (25th percentile): {stats_raw['q1']:.2f}%")
    print(f"Q3 (75th percentile): {stats_raw['q3']:.2f}%")

    print(f"\nTotal pairs processed: {len(data)}")
    print(f"Results saved to: {output_path}")


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_json> <output_json>", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    process_json_file(input_path, output_path)


if __name__ == "__main__":
    main()
