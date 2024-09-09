# Expert Construction of LLaMA-MoE-V2

This documentation provides the procedures to convert a LLaMA model to LLaMA-MoE-V2.



## 1. Get Router Weights

### K-means Centroids

Get the router weights through k-means clustering on the `hidden_states` of all layer inputs by running:

```bash
sbatch scripts/expert_construction_v2/get_gates/hidden_clustering.sh
```

### Random Features

Get the router weights through random selection of `hidden_states` among all layer inputs by running:

```bash
sbatch scripts/expert_construction_v2/get_gates/random_selection.sh
```



## 2. Split Neurons

### Gradient Split Plus

This strategy splits the neurons according to their importance scores on different token batches.

You should first run the following script to get the importance scores of all experts:

(Remember to pass the `--gate_weights_file` argument, where the file is generated from the *Get Router Weights* step.)

```bash
sbatch scripts/expert_construction_v2/split/split_gradient_get_grads_v2.sh
```



Then, you can run the following scripts to get the indices splits accordingly:

(Remember to pass the `--score_file` argument, where the file is generated from the above step.)

| MoE Type | Script                                                       |
| -------- | ------------------------------------------------------------ |
| Vanilla  | `sbatch scripts/expert_construction_v2/split/split_gradient_v2.sh` |
| Residual | `sbatch scripts/expert_construction_v2/split/split_gradient_residual_v2.sh` |



## 3. Convert MoE

### Convert to Vanilla LLaMA-MoE-V2

Just run the following script:

```bash
sbatch scripts/expert_construction_v2/convert/convert_mixtral_v2.sh
```

There are some arguments that you should notice:

- **`--gate_weights_file`:** This determines the initialization strategy of routers in the converted MoE model. If not specified, the MLP gates will be initialized randomly using *kaiming initialization*.
- **`--neuron_indices_file`:** This determines the indices of neurons in the original dense model for converted MLP experts. If not specified, the MLP experts will be split sequentially & uniformly (which is a very naive strategy).

Note that if the *Gradient Split Plus* strategy is used, you must specify `--gate_weights_file` as the path to the gate weights generated in the *Get Router Weights* step, and `--neuron_indices_file` as the generated `neuron_indices.pt` file accordingly.



### Convert to Residual LLaMA-MoE-V2

This is almost the same as the above. Just run the following script:

```bash
scripts/expert_construction_v2/convert/convert_mixtral_residual_v2.sh
```

The only difference is that you should always pass both `--gate_weights_file` and `--neuron_indices_file` arguments, as this script is specifically designed for the *Gradient Split Plus* strategy.



### Convert Attention MoE

The conversion of Attention MoE is performed on an existing converted MoE model (where the MLP has already been converted into MoE). You just need to run the following script:

```bash
sbatch scripts/expert_construction_v2/convert/convert_mixtral_attn_moe.sh
```

Note that the argument `--model_path` should be pointed to an already converted MoE model.



## 4. Align Hidden Distribution

To align a converted MoE model with the original dense model, you need to first get the original feature distribution by running ,

```bash
sbatch scripts/expert_construction_v2/align/get_hidden_distribution.sh
```

After that, a `distribution.pt` file will be saved to the disk. This file can be reused to align all converted models based on the original dense model, which means that you don’t need to run the script multiple times.



After obtaining the original distribution, you can run the following script to align a converted MoE model:

```bash
sbatch scripts/expert_construction_v2/align/align_converted_model.sh
```

The key arguments to be passed include:

- **`--model_name_or_path`:** Path to the converted MoE model to align.
- **`--reference_distribution_file`:** The `distribution.pt` file generated by the last step.



## Example Full Pipeline

### Convert LLaMA into Vanilla LLaMA-MoE-v2 with Gradient Split Plus Strategy

| Order | Step                       | Script                                                       |
| ----- | -------------------------- | ------------------------------------------------------------ |
| 1     | Get gate weights           | `sbatch scripts/expert_construction_v2/get_gates/hidden_clustering.sh` |
| 2     | Get neuron importance      | `sbatch scripts/expert_construction_v2/split/split_gradient_get_grads_v2.sh` |
| 3     | Get neuron indices         | `sbatch scripts/expert_construction_v2/split/split_gradient_v2.sh` |
| 4     | Convert MLP to vanilla MoE | `sbatch scripts/expert_construction_v2/convert/convert_mixtral_v2.sh` |
| 5     | Convert Attention to MoE   | `sbatch scripts/expert_construction_v2/convert/convert_mixtral_attn_moe.sh` |
| 6     | Get Distribution to align  | `sbatch scripts/expert_construction_v2/align/get_hidden_distribution.sh` |
| 7     | Align the Distribution     | `sbatch scripts/expert_construction_v2/align/align_converted_model.sh` |



### Convert LLaMA into Vanilla LLaMA-MoE-v2 Sequentially with Random Gate

| Order | Step                       | Script                                                       |
| ----- | -------------------------- | ------------------------------------------------------------ |
| 1     | Convert MLP to vanilla MoE | `sbatch scripts/expert_construction_v2/convert/convert_mixtral_v2.sh` |
| 2     | Convert Attention to MoE   | `sbatch scripts/expert_construction_v2/convert/convert_mixtral_attn_moe.sh` |
| 3     | Get Distribution to align  | `sbatch scripts/expert_construction_v2/align/get_hidden_distribution.sh` |
| 4     | Align the Distribution     | `sbatch scripts/expert_construction_v2/align/align_converted_model.sh` |