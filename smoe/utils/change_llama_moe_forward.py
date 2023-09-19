import torch
from transformers.utils import logging

from smoe.models.llama_moefication import BaseMoEModelOutputWithPast

logger = logging.get_logger(__name__)


def forward_mlp_moe_gate_with_hidden_states_recording(self, x, padding_mask, **kwargs):
    # fmt: off
    self.samples_cnt += torch.sum(padding_mask).item()  ####################################

    """先计算所有专家的权重值"""
    logits = self.gate_network(x)  # gate计算出的权重

    """选出前k个权重，并计算各个专家的分数scores"""
    top_logits, top_indices = logits.topk(min(self.num_selects + 1, self.num_experts), dim=1)  # 选择并排序前k+1个权重
    top_k_logits = top_logits[:, :self.num_selects]
    top_k_indices = top_indices[:, :self.num_selects]
    top_k_scores = self.softmax(top_k_logits) if self.use_softmax else top_k_logits  # 对前k个计算softmax，得到对应的分数

    zeros = torch.zeros_like(logits, requires_grad=True, device=logits.device)
    scores_filtered = zeros.scatter(dim=1, index=top_k_indices, src=top_k_scores)  # shape(batch_size, num_experts)
    scores_filtered = scores_filtered[padding_mask]  ###############################################

    """计算importance"""
    importance = scores_filtered.sum(0)  # shape(num_experts)
    self.importance_sum += scores_filtered.detach().sum(0)

    """计算load"""
    load = (scores_filtered > 0).sum(0)  # shape(num_experts)
    self.load_sum += (scores_filtered.detach() > 0).sum(0)

    """计算balance loss"""
    importance_loss = self.cv_squared(importance) * self.balance_loss_weight
    load_loss = self.cv_squared(load) * self.balance_loss_weight
    balance_loss = importance_loss + load_loss

    self.importance_loss_sum += importance_loss.detach()
    self.load_loss_sum += load_loss.detach()

    return {
        "topK_indices": top_k_indices,
        "topK_scores": top_k_scores,
        "balance_loss": balance_loss,
    }
    # fmt: on


def forward_linear_glu_moe_layer_with_padding_mask(
    self,
    x,
    padding_mask,
):
    # fmt: off
    original_shape = x.shape[:-1]
    x = x.reshape(-1, self.input_size)  # shape(batch_size*seq_len, input_size)
    padding_mask = padding_mask.reshape(-1)  # shape(batch_size*seq_len)

    gate_outputs = self.gate(x, padding_mask)  # 计算被选出的专家及其分数，以及gate的loss
    y = self.calculator(x, **gate_outputs)  # 合并各专家的计算结果

    y = y.reshape(original_shape + (self.output_size,))  # shape(batch_size, seq_len, output_size)
    return y, gate_outputs["balance_loss"]
    # fmt: on


def forward_llama_moe_decoder_with_padding_mask(
    self,
    hidden_states,
    padding_mask,  # ----- add padding_mask -----
    attention_mask=None,
    position_ids=None,
    past_key_value=None,
    output_attentions=False,
    use_cache=False,
):
    residual = hidden_states
    hidden_states = self.input_layernorm(hidden_states)

    # Self Attention
    hidden_states, self_attn_weights, present_key_value = self.self_attn(
        hidden_states=hidden_states,
        attention_mask=attention_mask,
        position_ids=position_ids,
        past_key_value=past_key_value,
        output_attentions=output_attentions,
        use_cache=use_cache,
    )
    hidden_states = residual + hidden_states

    # Fully Connected
    residual = hidden_states
    hidden_states = self.post_attention_layernorm(hidden_states)
    ###########################################################
    # ----- add padding_mask -----
    hidden_states, gate_loss = self.mlp(hidden_states, padding_mask)
    ###########################################################
    hidden_states = residual + hidden_states

    outputs = (
        hidden_states,
        gate_loss,
    )

    if output_attentions:
        outputs += (self_attn_weights,)

    if use_cache:
        outputs += (present_key_value,)

    return outputs


def forward_llama_moe_model_with_padding_mask(
    self,
    input_ids=None,
    attention_mask=None,
    position_ids=None,
    past_key_values=None,
    inputs_embeds=None,
    use_cache=None,
    output_attentions=None,
    output_hidden_states=None,
    return_dict=None,
):
    output_attentions = (
        output_attentions
        if output_attentions is not None
        else self.config.output_attentions
    )
    output_hidden_states = (
        output_hidden_states
        if output_hidden_states is not None
        else self.config.output_hidden_states
    )
    use_cache = use_cache if use_cache is not None else self.config.use_cache

    return_dict = (
        return_dict if return_dict is not None else self.config.use_return_dict
    )

    # retrieve input_ids and inputs_embeds
    if input_ids is not None and inputs_embeds is not None:
        raise ValueError(
            "You cannot specify both decoder_input_ids and decoder_inputs_embeds at"
            " the same time"
        )
    elif input_ids is not None:
        batch_size, seq_length = input_ids.shape
    elif inputs_embeds is not None:
        batch_size, seq_length, _ = inputs_embeds.shape
    else:
        raise ValueError(
            "You have to specify either decoder_input_ids or decoder_inputs_embeds"
        )

    seq_length_with_past = seq_length
    past_key_values_length = 0

    if past_key_values is not None:
        past_key_values_length = past_key_values[0][0].shape[2]
        seq_length_with_past = seq_length_with_past + past_key_values_length

    if position_ids is None:
        device = input_ids.device if input_ids is not None else inputs_embeds.device
        position_ids = torch.arange(
            past_key_values_length,
            seq_length + past_key_values_length,
            dtype=torch.long,
            device=device,
        )
        position_ids = position_ids.unsqueeze(0).view(-1, seq_length)
    else:
        position_ids = position_ids.view(-1, seq_length).long()

    if inputs_embeds is None:
        inputs_embeds = self.embed_tokens(input_ids)

    # embed positions
    ###########################################################
    padding_mask = attention_mask.bool()  # ----- add padding_mask -----
    ###########################################################
    if attention_mask is None:
        attention_mask = torch.ones(
            (batch_size, seq_length_with_past),
            dtype=torch.bool,
            device=inputs_embeds.device,
        )
    attention_mask = self._prepare_decoder_attention_mask(
        attention_mask,
        (batch_size, seq_length),
        inputs_embeds,
        past_key_values_length,
    )

    hidden_states = inputs_embeds
    gate_loss = 0.0

    if self.gradient_checkpointing and self.training:
        if use_cache:
            logger.warning_once(
                "`use_cache=True` is incompatible with gradient checkpointing."
                " Setting `use_cache=False`..."
            )
            use_cache = False

    # decoder layers
    all_hidden_states = () if output_hidden_states else None
    all_self_attns = () if output_attentions else None
    next_decoder_cache = () if use_cache else None

    for idx, decoder_layer in enumerate(self.layers):
        if output_hidden_states:
            all_hidden_states += (hidden_states,)

        past_key_value = past_key_values[idx] if past_key_values is not None else None

        if self.gradient_checkpointing and self.training:

            def create_custom_forward(module):
                def custom_forward(*inputs):
                    # None for past_key_value
                    return module(*inputs, output_attentions, None)

                return custom_forward

            ###########################################################
            layer_outputs = torch.utils.checkpoint.checkpoint(
                create_custom_forward(decoder_layer),
                hidden_states,
                padding_mask,  # ----- add padding_mask -----
                attention_mask,
                position_ids,
                None,
            )
        else:
            layer_outputs = decoder_layer(
                hidden_states,
                padding_mask,  # ----- add padding_mask -----
                attention_mask=attention_mask,
                position_ids=position_ids,
                past_key_value=past_key_value,
                output_attentions=output_attentions,
                use_cache=use_cache,
            )
            ###########################################################

        hidden_states = layer_outputs[0]
        if layer_outputs[1] is not None:
            gate_loss += layer_outputs[1]

        if use_cache:
            next_decoder_cache += (layer_outputs[3 if output_attentions else 2],)

        if output_attentions:
            all_self_attns += (layer_outputs[2],)

    hidden_states = self.norm(hidden_states)

    # add hidden states from the last decoder layer
    if output_hidden_states:
        all_hidden_states += (hidden_states,)

    next_cache = next_decoder_cache if use_cache else None
    if not return_dict:
        return tuple(
            v
            for v in [hidden_states, next_cache, all_hidden_states, all_self_attns]
            if v is not None
        )
    return BaseMoEModelOutputWithPast(
        last_hidden_state=hidden_states,
        gate_loss=gate_loss,
        past_key_values=next_cache,
        hidden_states=all_hidden_states,
        attentions=all_self_attns,
    )