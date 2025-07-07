import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict
from tqdm import tqdm

@dataclass
class CodePair:
    decompiled_code: str
    original_code: str
    dep: str

    def get_decompiled_source(self) -> str:
        return self.dep + self.decompiled_code

    def get_original_source(self) -> str:
        return self.dep + self.original_code

def compile_and_objdump(source_code: str, output_dir: Path, prefix: str) -> Optional[Tuple[str, str]]:
    """Compile source code and get objdump output"""
    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".c", mode="w", encoding="utf-8") as temp_file:
        temp_file.write(source_code)
        temp_file_path = temp_file.name

    obj_path = output_dir / f"{prefix}.o"
    try:
        # compile
        compile_command = ["gcc", "-c", "-O0", "-o", str(obj_path), temp_file_path]
        subprocess.run(compile_command, check=True, capture_output=True, text=True)

        # get objdump output
        objdump_command = ["objdump", "-d", str(obj_path)]
        objdump_output = subprocess.run(objdump_command, check=True, capture_output=True, text=True)
        
        return str(obj_path), objdump_output.stdout
    except subprocess.CalledProcessError as e:
        return None
    finally:
        # delete temporary file
        os.unlink(temp_file_path)

def process_code_pair(data: CodePair, output_dir: Path) -> Optional[Dict]:
    try:
        # process decompiled code
        decompiled_result = compile_and_objdump(
            data.get_decompiled_source(),
            output_dir,
            "decompiled"
        )
        if not decompiled_result:
            return None

        # process original code
        original_result = compile_and_objdump(
            data.get_original_source(),
            output_dir,
            "original"
        )
        if not original_result:
            return None

        decompiled_obj_path, decompiled_asm = decompiled_result
        original_obj_path, original_asm = original_result

        return {
            "decompiled_obj_path": decompiled_obj_path,
            "decompiled_asm": decompiled_asm,
            "original_obj_path": original_obj_path,
            "original_asm": original_asm,
            "decompiled_code": data.decompiled_code,
            "original_code": data.original_code,
            "dep": data.dep
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return None

def main():
    opt = "o2"
    input_path = Path(f"dataset/{opt}_decompiled_testset.json")
    output_dir = Path("compiled_pairs")
    output_dir.mkdir(exist_ok=True)

    try:
        with open(input_path, "r") as f:
            json_data = json.load(f)
    except Exception as e:
        print(f"Failed to load dataset: {e}")
        return

    success_count = 0
    error_count = 0
    successful_pairs = []
    failed_pairs = []  # save failed cases

    for item in tqdm(json_data, desc="Processing code pairs"):
        data = CodePair(
            decompiled_code=item["decompiled_code"],
            original_code=item["original_code"],
            dep=item["dep"]
        )

        result = process_code_pair(data, output_dir)
        if result:
            success_count += 1
            successful_pairs.append(result)
        else:
            error_count += 1
            # save failed cases
            failed_pairs.append({
                "decompiled_code": data.decompiled_code,
                "original_code": data.original_code,
                "dep": data.dep
            })

    # save success pairs
    output_path = Path(f"dataset/{opt}_compiled_pairs.json")
    with open(output_path, "w") as f:
        json.dump(successful_pairs, f, indent=2)

    # save failed pairs
    failed_output_path = Path(f"dataset/{opt}_failed_compilation_pairs.json")
    with open(failed_output_path, "w") as f:
        json.dump(failed_pairs, f, indent=2)

    print(f"\nProcessing results:")
    print(f"success: {success_count}")
    print(f"failed: {error_count}")
    print(f"success rate: {success_count / (success_count + error_count) * 100:.2f}%")
    print(f"success pairs are saved to {output_path}")
    print(f"failed pairs are saved to {failed_output_path}")

if __name__ == "__main__":
    main() 