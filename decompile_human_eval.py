import json
import logging
import os
import sys

from argparse import ArgumentParser
from transformers import AutoTokenizer
from tqdm import tqdm
from vllm import LLM, SamplingParams

logger = logging.getLogger(__name__)

def parse_args() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument("--model_path", type=str)
    parser.add_argument("--dtype", type=str, default="bfloat16")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--max_input_len", type=int, default=8192)
    parser.add_argument("--max_total_tokens", type=int, default=8800)
    parser.add_argument("--max_batch_prefill_tokens", type=int, default=72000)
    parser.add_argument("--gpus", type=int, default=4)
    parser.add_argument("--max_new_tokens", type=int, default=512)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--testset_path", type=str)
    parser.add_argument("--num_workers", type=int, default=16)
    parser.add_argument("--gpu_memory_utilization", type=float, default=0.95)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--output_dir", type=str)
    return parser.parse_args()

def filter_o0_data(json_data: list[dict]) -> list[dict]:
    """
    Filter O0 test cases
    Note: Extract only C language test cases
    """
    return [item for item in json_data if item.get("opt") == "O0" and item.get("language") == "c"]

def filter_o2_data(json_data: list[dict]) -> list[dict]:
    """
    Filter O2 test cases
    Note: Extract only C language test cases
    """
    return [item for item in json_data if item.get("opt") == "O2" and item.get("language") == "c"]

def load_dataset(path: str) -> list[dict]: 
    """
    Load dataset from path
    """
    with open(path, "r") as dataset_file:
        dataset = json.load(dataset_file)
    return dataset 

def prompt_template(asm_code: str) -> str: 
    """
    Prompt template for decompilation
    """
    before = "# This is the assembly code:\n"
    after = "\n# What is the source code?\n"
    return before + asm_code + after

def decompile(data: list[dict], llm: LLM, sampling_params: SamplingParams) -> list[dict]:
    """
    Decompile test cases using LLM
    """
    results = []
    for item in tqdm(data):
        outputs = llm.generate(prompt_template(item["asm"]), sampling_params)
        decompiled_code = outputs[0].outputs[0].text
        results.append({
            "decompiled_code": decompiled_code,
            "dep": item["func_dep"],
            "original_code": item["func"],
            "test": item["test"],
            "original_asm": item["asm"],
        })

    logger.info(f"Decompiled {len(results)} test cases")
    return results

def load_and_filter_testsets(testset_path: str) -> tuple[list[dict], list[dict]]:
    """
    Load and filter testsets into O0 and O2 datasets
    """
    testset = load_dataset(testset_path)
    o0_testset = filter_o0_data(testset)
    logger.info(f"Loaded {len(o0_testset)} O0 test cases")

    o2_testset = filter_o2_data(testset)
    logger.info(f"Loaded {len(o2_testset)} O2 test cases")
    
    return o0_testset, o2_testset

def load_model_and_tokenizer(args: ArgumentParser) -> tuple[LLM, SamplingParams]:
    """
    Load model, tokenizer and create sampling parameters
    """
    tokenizer = AutoTokenizer.from_pretrained(args.model_path)
    stop_sequences = [tokenizer.eos_token]
    logger.info(f"Loaded tokenizer: {tokenizer}, stop_sequences: {stop_sequences}")

    llm = LLM(
        model=args.model_path,
        tensor_parallel_size=args.gpus,
        max_model_len=args.max_input_len,
        gpu_memory_utilization=args.gpu_memory_utilization,
    )

    sampling_params = SamplingParams(
        temperature=args.temperature,
        max_tokens=args.max_new_tokens,
        stop=stop_sequences,
    )

    logger.info(f"Loaded model: {args.model_path}, sampling_params: {sampling_params}")

    return llm, sampling_params

def save_decompiled_testsets(output_dir: str, o0_testset: list[dict], o2_testset: list[dict]) -> int:
    """
    Save decompiled test sets to output directory
    """
    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            logger.info(f"Saving {len(o0_testset)} O0 decompiled test cases to {output_dir}/o0_decompiled_testset.json")

        with open(output_dir + "/o0_decompiled_testset.json", "w") as f:
            json.dump(o0_testset, f, indent=4)
            logger.info(f"Saved {len(o0_testset)} O0 decompiled test cases to {output_dir}/o0_decompiled_testset.json")

        with open(output_dir + "/o2_decompiled_testset.json", "w") as f:
            json.dump(o2_testset, f, indent=4)
            logger.info(f"Saved {len(o2_testset)} O2 decompiled test cases to {output_dir}/o2_decompiled_testset.json")

    except Exception as e:
        logger.error(f"Failed to save decompiled test cases: {e}")
        return 1
    return 0

def run_eval_pipeline(args: ArgumentParser) -> int: 
    """
    Run evaluation pipeline
    """
    try:
        o0_testset, o2_testset = load_and_filter_testsets(args.testset_path)
    except Exception as e:
        logger.error(f"Failed to load dataset from {args.testset_path}: {e}")
        return 1

    # Load model and tokenizer
    try:
        llm, sampling_params = load_model_and_tokenizer(args)
    except Exception as e:
        logger.error(f"Failed to load model from {args.model_path}: {e}")
        return 1

    # Decompile testcases
    try:
        o0_decompiled_testset = decompile(o0_testset, llm, sampling_params)
        o2_decompiled_testset = decompile(o2_testset, llm, sampling_params)
    except Exception as e:
        logger.error(f"Failed to decompile test cases: {e}")
        return 1

    # Save decompiled testsets
    return save_decompiled_testsets(args.output_dir, o0_decompiled_testset, o2_decompiled_testset)

def main():
    args = parse_args()
    ret = run_eval_pipeline(args)
    sys.exit(ret)


if __name__ == "__main__":
    main()