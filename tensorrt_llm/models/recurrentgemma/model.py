# SPDX-FileCopyrightText: Copyright (c) 2022-2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from collections import OrderedDict
from typing import List

import tensorrt as trt

from ..._common import default_net
from ..._utils import str_dtype_to_trt
from ...functional import (Tensor, arange, concat, expand,
                           gather_last_token_logits, shape, tanh, unsqueeze)
from ...layers import (Attention, AttentionMaskType, AttentionParams, Embedding,
                       GatedMLP, KeyValueCacheParams, Linear,
                       PositionEmbeddingType, Recurrent, RmsNorm)
from ...module import Module, ModuleList
from ..generation_mixin import GenerationMixin
from ..modeling_utils import PretrainedConfig, PretrainedModel


class ResidualLayer(Module):

    def __init__(self, config: PretrainedConfig, layer_idx: int):
        super().__init__()
        layer_type_len = len(config.layer_types)
        self.temporal_block_type = config.layer_types[layer_idx %
                                                      layer_type_len]

        self.input_layernorm = RmsNorm(normalized_shape=config.hidden_size,
                                       eps=config.norm_epsilon,
                                       dtype=config.dtype)

        if self.temporal_block_type == 'recurrent':
            self.temporal_block = Recurrent(
                width=config.hidden_size,
                lru_width=config.rnn_hidden_size,
                d_conv=config.conv_kernel,
                num_heads=config.num_attention_heads,
                dtype=config.dtype,
                tp_group=config.mapping.tp_group,
                tp_size=config.mapping.tp_size,
                tp_rank=config.mapping.tp_rank)
        elif self.temporal_block_type == 'attention':
            layer_types = config.layer_types * (
                (layer_idx + 1) // layer_type_len)
            layer_types = layer_types + config.layer_types[0:(
                (layer_idx + 1) % layer_type_len)]
            attention_layer_idx = layer_types.count('attention') - 1
            self.temporal_block = Attention(
                local_layer_idx=attention_layer_idx,
                hidden_size=config.hidden_size,
                num_attention_heads=config.num_attention_heads,
                num_kv_heads=config.num_key_value_heads,
                max_position_embeddings=config.max_position_embeddings,
                dtype=config.dtype,
                attention_mask_type=AttentionMaskType.causal,
                position_embedding_type=PositionEmbeddingType.rope_gpt_neox,
                rotary_embedding_percentage=config.rotary_percentage,
                tp_group=config.mapping.tp_group,
                tp_size=config.mapping.tp_size,
                tp_rank=config.mapping.tp_rank,
                quant_mode=config.quant_mode,
                bias=False,
                dense_bias=True)
        else:
            raise ValueError(
                'RecurrentGemma only support "recurrent" and "attention" blocks.'
            )

        self.post_layernorm = RmsNorm(normalized_shape=config.hidden_size,
                                      eps=config.norm_epsilon,
                                      dtype=config.dtype)

        self.mlp = GatedMLP(hidden_size=config.hidden_size,
                            ffn_hidden_size=config.intermediate_size,
                            hidden_act=config.hidden_act,
                            dtype=config.dtype,
                            tp_group=config.mapping.tp_group,
                            tp_size=config.mapping.tp_size,
                            quant_mode=config.quant_mode)

    def forward(self,
                hidden_states,
                use_cache=False,
                attention_mask=None,
                kv_cache_params=None,
                attention_params=None,
                conv_state=None,
                lru_state=None,
                host_request_types=None,
                last_token_ids=None,
                host_context_lengths=None,
                slot_mapping=None,
                conv_indices=None):

        residual = hidden_states

        hidden_states = self.input_layernorm(hidden_states)

        if self.temporal_block_type == 'recurrent':
            temporal_output, present_conv, present_lru = self.temporal_block(
                hidden_states,
                conv_state=conv_state,
                lru_state=lru_state,
                host_request_types=host_request_types,
                last_token_ids=last_token_ids,
                host_context_lengths=host_context_lengths,
                slot_mapping=slot_mapping,
                conv_indices=conv_indices,
            )
        else:
            present_conv, present_lru = None, None

        if self.temporal_block_type == 'attention':
            temporal_output, present_kv = self.temporal_block(
                hidden_states,
                attention_mask=attention_mask,
                use_cache=use_cache,
                kv_cache_params=kv_cache_params,
                attention_params=attention_params)
        else:
            present_kv = None

        hidden_states = residual + temporal_output

        residual = hidden_states
        hidden_states = self.post_layernorm(hidden_states)
        hidden_states = self.mlp(hidden_states)
        hidden_states = residual + hidden_states

        return hidden_states, present_kv, present_conv, present_lru


class RecurrentGemmaModel(Module):

    def __init__(self, config: PretrainedConfig) -> None:
        super().__init__()
        self.d_conv = config.conv_kernel
        self.lru_width = config.rnn_hidden_size
        n_layer = config.num_hidden_layers

        self.vocab_embedding = Embedding(config.vocab_size,
                                         config.hidden_size,
                                         dtype=config.dtype)
        self.layers = ModuleList(
            [ResidualLayer(config, layer_idx=i) for i in range(n_layer)])

        self.norm_f = RmsNorm(normalized_shape=config.hidden_size,
                              eps=config.norm_epsilon,
                              dtype=config.dtype)

    def forward(self,
                input_ids,
                use_cache=False,
                attention_mask=None,
                kv_cache_params=None,
                attention_params=None,
                conv_states=None,
                lru_states=None,
                host_request_types=None,
                last_token_ids=None,
                host_context_lengths=None,
                slot_mapping=None):

        hidden_states = self.vocab_embedding(input_ids)

        # Get conv state indices
        indices = None
        if not default_net().plugin_config.mamba_conv1d_plugin:
            batch_size = shape(input_ids, 0)
            indices = expand(
                unsqueeze(arange(0, self.d_conv - 1, dtype='int32'), 0),
                concat([batch_size, self.d_conv - 1]))
            offsets = expand(unsqueeze(last_token_ids, 1),
                             concat([batch_size, self.d_conv - 1]))
            indices = unsqueeze(indices + offsets, 1)
            indices = expand(
                indices, concat([batch_size, self.lru_width, self.d_conv - 1]))

        present_kvs, present_convs, present_lrus = [], [], []
        for layer, past_kv, past_conv, past_lru in zip(
                self.layers, kv_cache_params.past_key_value, conv_states,
                lru_states):
            hidden_states, present_kv, present_conv, present_lru = layer(
                hidden_states,
                use_cache,
                attention_mask,
                kv_cache_params=KeyValueCacheParams(
                    past_key_value=[past_kv],
                    host_past_key_value_lengths=kv_cache_params.
                    host_past_key_value_lengths,
                    host_max_attention_window_sizes=kv_cache_params.
                    host_max_attention_window_sizes,
                    host_sink_token_length=kv_cache_params.
                    host_sink_token_length,
                    kv_cache_block_offsets=kv_cache_params.
                    kv_cache_block_offsets,
                    host_kv_cache_block_offsets=kv_cache_params.
                    host_kv_cache_block_offsets,
                    host_kv_cache_pool_pointers=kv_cache_params.
                    host_kv_cache_pool_pointers,
                    cache_indirection=kv_cache_params.cache_indirection),
                attention_params=attention_params,
                conv_state=past_conv,
                lru_state=past_lru,
                host_request_types=host_request_types,
                last_token_ids=last_token_ids,
                host_context_lengths=host_context_lengths,
                slot_mapping=slot_mapping,
                conv_indices=indices)
            present_kvs.append(present_kv)
            present_convs.append(present_conv)
            present_lrus.append(present_lru)

        hidden_states = self.norm_f(hidden_states)
        return hidden_states, tuple(present_kvs), tuple(present_convs), tuple(
            present_lrus)


class RecurrentGemmaForCausalLM(PretrainedModel):

    def __init__(self, config: PretrainedConfig):
        super().__init__(config)
        dtype = config.dtype
        logits_dtype = config.logits_dtype
        if isinstance(dtype, str):
            self.dtype = str_dtype_to_trt(dtype)
        else:
            assert isinstance(dtype, trt.DataType)
            self.dtype = dtype

        assert len(config.layer_types) > 0
        layer_types = config.layer_types
        layer_types = layer_types * (config.num_hidden_layers //
                                     len(layer_types))
        layer_types = layer_types + layer_types[0:(config.num_hidden_layers %
                                                   len(layer_types))]
        self.layer_types = layer_types

        self.config = config
        self.gather_context_logits = False
        self.logits_soft_cap = config.logits_soft_cap

        if isinstance(logits_dtype, str):
            self._logits_dtype = str_dtype_to_trt(logits_dtype)
        else:
            assert isinstance(logits_dtype, trt.DataType)
            self._logits_dtype = logits_dtype

        self.backbone = RecurrentGemmaModel(config)
        self.lm_head = Linear(config.hidden_size,
                              config.vocab_size,
                              bias=False,
                              dtype=dtype,
                              gather_output=False)

    def __post_init__(self):
        return

    def forward(self,
                input_ids,
                position_ids=None,
                use_cache=False,
                attention_mask=None,
                kv_cache_params=None,
                attention_params=None,
                conv_states=None,
                rnn_states=None,
                host_request_types=None,
                last_token_ids=None,
                last_token_ids_for_logits=None,
                host_context_lengths=None,
                slot_mapping=None):
        hidden_states, present_kvs, present_convs, present_rnns = self.backbone(
            input_ids, use_cache, attention_mask, kv_cache_params,
            attention_params, conv_states, rnn_states, host_request_types,
            last_token_ids, host_context_lengths, slot_mapping)

        if not self.gather_context_logits:
            hidden_states = gather_last_token_logits(
                hidden_states, last_token_ids_for_logits,
                default_net().plugin_config.remove_input_padding)

        lm_logits = self.lm_head(hidden_states)
        lm_logits = tanh(
            lm_logits / self.logits_soft_cap) * self.logits_soft_cap
        lm_logits.mark_output('logits', self._logits_dtype)
        if not default_net().plugin_config.paged_kv_cache:
            for i, present_kv in enumerate(present_kvs):
                if present_kv is not None:
                    present_kv.mark_output(f'present_key_value_{i}', self.dtype)

        if not default_net().plugin_config.paged_state:
            for i, present_conv in enumerate(present_convs):
                if present_conv is not None:
                    present_conv.mark_output(f'present_conv_state_{i}',
                                             self.dtype)
            for i, present_rnn in enumerate(present_rnns):
                if present_rnn is not None:
                    present_rnn.mark_output(f'present_rnn_state_{i}',
                                            self.dtype)

        return (lm_logits, present_kvs, present_convs, present_rnns)

    def prepare_recurrent_inputs(self, max_batch_size, num_profiles, mapping):
        use_mamba_conv1d_plugin = default_net(
        ).plugin_config.mamba_conv1d_plugin

        default_range = GenerationMixin.default_range
        batch_range = [default_range(max_batch_size)] * num_profiles

        conv_states = []
        rnn_states = []
        dim = self.config.rnn_hidden_size // mapping.tp_size
        if use_mamba_conv1d_plugin:
            conv_state_dim_range = OrderedDict([
                ('batch_size', batch_range),
                ('kernel_size', [self.config.conv_kernel - 1] * num_profiles),
                ('dim_size', [dim] * num_profiles),
            ])
        else:
            conv_state_dim_range = OrderedDict([
                ('batch_size', batch_range),
                ('dim_size', [dim] * num_profiles),
                ('kernel_size', [self.config.conv_kernel - 1] * num_profiles),
            ])

        rnn_state_dim_range = OrderedDict([
            ('batch_size', batch_range),
            ('dim_size', [dim] * num_profiles),
        ])
        one_dim_range = OrderedDict([
            ('buffer_count', [1] * num_profiles),
        ])

        for i in range(self.config.num_hidden_layers):
            if self.layer_types[i] == 'recurrent':
                if default_net().plugin_config.paged_state:
                    conv_state = Tensor(name=f'conv_state_ptr_{i}',
                                        dtype=str_dtype_to_trt('int64'),
                                        shape=[1],
                                        dim_range=one_dim_range)

                    rnn_state = Tensor(name=f'rnn_state_ptr_{i}',
                                       dtype=str_dtype_to_trt('int64'),
                                       shape=[1],
                                       dim_range=one_dim_range)
                else:
                    if use_mamba_conv1d_plugin:
                        conv_state = Tensor(name=f'past_conv_state_{i}',
                                            dtype=self.dtype,
                                            shape=[
                                                -1, self.config.conv_kernel - 1,
                                                self.config.rnn_hidden_size
                                            ],
                                            dim_range=conv_state_dim_range)
                    else:
                        conv_state = Tensor(name=f'past_conv_state_{i}',
                                            dtype=self.dtype,
                                            shape=[
                                                -1, self.config.rnn_hidden_size,
                                                self.config.conv_kernel - 1
                                            ],
                                            dim_range=conv_state_dim_range)

                    rnn_state = Tensor(name=f'past_rnn_state_{i}',
                                       dtype=str_dtype_to_trt('float32'),
                                       shape=[-1, self.config.rnn_hidden_size],
                                       dim_range=rnn_state_dim_range)
            else:
                conv_state, rnn_state = None, None
            conv_states.append(conv_state)
            rnn_states.append(rnn_state)

        slot_mapping = None
        if default_net().plugin_config.paged_state:
            slot_mapping = Tensor(
                name='slot_mapping',
                dtype=trt.int32,
                shape=[-1],
                dim_range=OrderedDict([('batch_size', batch_range)]),
            )

        return_dict = {
            'conv_states': conv_states,
            'rnn_states': rnn_states,
            'slot_mapping': slot_mapping,
        }
        return return_dict

    def prepare_inputs(self,
                       max_batch_size,
                       max_input_len,
                       max_seq_len,
                       use_cache,
                       max_beam_width: int = 1,
                       max_num_tokens: int = None,
                       opt_num_tokens: int = None,
                       prompt_embedding_table_size: int = 0,
                       max_draft_len: int = 0,
                       gather_context_logits: bool = False,
                       gather_generation_logits: bool = False,
                       lora_target_modules: List[str] = None):
        '''@brief: Prepare inputs Tensors for the model, the given sizes are used to determine the
            ranges of the dimensions of when using TRT dynamic shapes.

            @return: a list contains values which can be fed into the self.forward()
        '''
        assert max_beam_width == 1, "We don't support beam search for the RecurrentGemma model."

        remove_input_padding = default_net().plugin_config.remove_input_padding
        use_gpt_attention_plugin = default_net(
        ).plugin_config.gpt_attention_plugin
        use_gemm_plugin = default_net().plugin_config.gemm_plugin
        paged_kv_cache = default_net().plugin_config.paged_kv_cache
        tokens_per_block = default_net().plugin_config.tokens_per_block
        multiple_profiles = default_net().plugin_config.multiple_profiles
        streamingllm = default_net().plugin_config.streamingllm
        use_mamba_conv1d_plugin = default_net(
        ).plugin_config.mamba_conv1d_plugin

        self.gather_context_logits = gather_context_logits
        mapping = self.config.mapping

        default_range = GenerationMixin.default_range
        batch_range = default_range(max_batch_size)
        bbd_range = [
            batch_range[i] * ((max_draft_len + 1) if i != 0 else 1)
            for i in range(len(batch_range))
        ]
        inlen_range_cxt = default_range(max_input_len)
        inlen_range_gen = [1, 1, max_draft_len + 1]

        # basic inputs
        enable_ctx_gen_opt_profiles = GenerationMixin.has_ctx_gen_opt_profiles(
            use_gpt_attention_plugin, use_gemm_plugin, remove_input_padding,
            paged_kv_cache)
        if max_num_tokens is None:
            max_num_tokens = max(
                max_input_len * max_batch_size,
                max_beam_width * (max_draft_len + 1) * max_batch_size)
        if enable_ctx_gen_opt_profiles:
            num_profiles = 2
            inlen_range = [inlen_range_cxt, inlen_range_gen]
            num_tokens_range_ctx = default_range(max_num_tokens)
            num_tokens_range_gen = default_range(
                max_batch_size * (max_draft_len + 1) * max_beam_width)
            num_tokens_range = [num_tokens_range_ctx, num_tokens_range_gen]
            position_ids_inlen_range = [inlen_range_cxt, [1, 1, 1]]
        else:
            max_bs_x_max_bw = max_batch_size * max_beam_width
            if opt_num_tokens is None:
                opt_num_tokens = max_bs_x_max_bw
            if multiple_profiles:
                if max_num_tokens > max_bs_x_max_bw:
                    num_tokens_range = [[1, max_bs_x_max_bw, max_bs_x_max_bw],
                                        [
                                            max_bs_x_max_bw, max_num_tokens,
                                            max_num_tokens
                                        ]]
                else:
                    num_tokens_range = [[1, max_num_tokens, max_num_tokens]]
            else:
                num_tokens_range = [[1, opt_num_tokens, max_num_tokens]]
            num_profiles = len(num_tokens_range)
            inlen_range = [[1, 1, max_input_len]] * num_profiles
            position_ids_inlen_range = [[1, 1, max_input_len]] * num_profiles
        bb_range = [batch_range] * num_profiles

        if remove_input_padding:
            assert use_mamba_conv1d_plugin, "mamba_conv1d_plugin is needed to support remove_input_padding"
            input_ids = Tensor(name='input_ids',
                               dtype=trt.int32,
                               shape=[-1],
                               dim_range=OrderedDict([
                                   ('num_tokens', num_tokens_range),
                               ]))
            position_ids = Tensor(name='position_ids',
                                  dtype=trt.int32,
                                  shape=[-1],
                                  dim_range=OrderedDict([
                                      ('position_ids_num_tokens_range',
                                       num_tokens_range),
                                  ]))
        else:
            input_ids = Tensor(name='input_ids',
                               dtype=trt.int32,
                               shape=[-1, -1],
                               dim_range=OrderedDict([
                                   ('batch_size_beam_width',
                                    [batch_range] * num_profiles),
                                   ('input_len', inlen_range),
                               ]))
            position_ids = Tensor(name='position_ids',
                                  dtype=trt.int32,
                                  shape=[-1, -1],
                                  dim_range=OrderedDict([
                                      ('batch_size_beam_width', bb_range),
                                      ('position_ids_inlen_range',
                                       position_ids_inlen_range),
                                  ]))

        # attention inputs
        num_attention_layers = self.layer_types.count('attention')
        attn_layer_idx = []
        for i in range(self.config.num_hidden_layers):
            if self.layer_types[i] == 'attention':
                attn_layer_idx.append(i)
        attention_inputs = self.prepare_attention_inputs(
            max_batch_size=max_batch_size,
            max_beam_width=max_beam_width,
            max_input_len=max_input_len,
            max_seq_len=max_seq_len,
            num_kv_heads=self.config.num_key_value_heads,
            head_size=self.config.head_size,
            num_layers=num_attention_layers,
            kv_dtype=str_dtype_to_trt(self.config.kv_dtype),
            num_profiles=num_profiles,
            enable_ctx_gen_opt_profiles=enable_ctx_gen_opt_profiles,
            remove_input_padding=remove_input_padding,
            use_gpt_attention_plugin=use_gpt_attention_plugin,
            paged_kv_cache=paged_kv_cache,
            tokens_per_block=tokens_per_block,
            mapping=mapping,
            streamingllm=streamingllm,
            attn_layer_idx=attn_layer_idx)

        kv_idx = 0
        past_key_value = []
        for i in range(self.config.num_hidden_layers):
            if self.layer_types[i] == 'attention' and not paged_kv_cache:
                past_key_value.append(
                    attention_inputs['past_key_value'][kv_idx])
                kv_idx += 1
            else:
                past_key_value.append(None)
        attention_inputs['past_key_value'] = past_key_value

        # recurrent inputs
        recurrent_inputs = self.prepare_recurrent_inputs(
            max_batch_size=max_batch_size,
            num_profiles=num_profiles,
            mapping=mapping,
        )

        if use_gpt_attention_plugin:
            host_request_types = attention_inputs['host_request_types']
        else:
            host_request_types = Tensor(
                name='host_request_types',
                dtype=trt.int32,
                shape=[-1],
                dim_range=OrderedDict([('batch_size_beam_width', bb_range)]),
            )

        last_token_ids = Tensor(
            name='last_token_ids',
            dtype=trt.int32,
            shape=[-1],
            dim_range=OrderedDict([
                ('batch_size_last_token_ids', [bbd_range] * num_profiles),
            ]),
        )
        last_token_ids_for_logits = None
        if not gather_context_logits:
            last_token_ids_for_logits = last_token_ids

        if use_gpt_attention_plugin and remove_input_padding:
            host_context_lengths = attention_inputs['host_context_lengths']
        elif use_mamba_conv1d_plugin and remove_input_padding:
            host_context_lengths = Tensor(
                name='host_context_lengths',
                dtype=trt.int32,
                shape=[-1],
                dim_range=OrderedDict([('batch_size_beam_width', bb_range)]),
            )
        else:
            host_context_lengths = None

        return_dict = {
            'input_ids':
            input_ids,
            'position_ids':
            position_ids,
            'use_cache':
            True,
            'attention_mask':
            attention_inputs['attention_mask'],
            'kv_cache_params':
            KeyValueCacheParams(
                past_key_value=attention_inputs['past_key_value'],
                host_past_key_value_lengths=attention_inputs[
                    'host_past_key_value_lengths'],
                host_max_attention_window_sizes=attention_inputs[
                    'host_max_attention_window_sizes'],
                host_sink_token_length=attention_inputs[
                    'host_sink_token_length'],
                kv_cache_block_offsets=attention_inputs[
                    'kv_cache_block_offsets'],
                host_kv_cache_block_offsets=attention_inputs[
                    'host_kv_cache_block_offsets'],
                host_kv_cache_pool_pointers=attention_inputs[
                    'host_kv_cache_pool_pointers'],
                cache_indirection=attention_inputs['cache_indirection'],
            ),
            'attention_params':
            AttentionParams(
                sequence_length=attention_inputs['sequence_length'],
                context_lengths=attention_inputs['context_lengths'],
                host_context_lengths=attention_inputs['host_context_lengths'],
                max_context_length=max_input_len,
                host_request_types=attention_inputs['host_request_types']),
            'conv_states':
            recurrent_inputs['conv_states'],
            'rnn_states':
            recurrent_inputs['rnn_states'],
            'host_request_types':
            host_request_types,
            'last_token_ids':
            last_token_ids,
            'last_token_ids_for_logits':
            last_token_ids_for_logits,
            'host_context_lengths':
            host_context_lengths,
            'slot_mapping':
            recurrent_inputs['slot_mapping'],
        }
        return return_dict
