import argparse

import torch

from smoe.utils.expert_construction.convert_llama_to_mixtral_residual import (
    convert_residual_safetensors,
)

if __name__ == "__main__":
    # fmt: off
    parser = argparse.ArgumentParser()
    parser.add_argument('--model_path', type=str)
    parser.add_argument('--save_path', type=str)
    parser.add_argument('--neuron_indices_file', type=str, default=None)
    parser.add_argument('--gate_weights_file', type=str, default=None)

    parser.add_argument('--moe_implementation_type', type=str, default='modulelist', choices=["modulelist", "megablocks", "scattermoe"])
    parser.add_argument('--num_experts', type=int, default=None)
    parser.add_argument('--top_k', type=int, default=None)

    args = parser.parse_args()
    print(args, "\n")

    neuron_indices = torch.load(args.neuron_indices_file)
    intermediate_size = len(neuron_indices[0][0])
    residual_intermediate_size = len(neuron_indices[0]["residual"])

    convert_residual_safetensors(
        args.model_path,
        args.save_path,
        num_experts=args.num_experts,
        intermediate_size=intermediate_size,
        residual_intermediate_size=residual_intermediate_size,
        top_k=args.top_k,
        moe_type=args.moe_implementation_type,
        neuron_indices=neuron_indices,
        gate_weights=None if args.gate_weights_file is None else torch.load(args.gate_weights_file),
    )
    print("Done!")
    # fmt: on
