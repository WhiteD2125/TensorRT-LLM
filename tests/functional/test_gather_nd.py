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
import unittest

import numpy as np

# isort: off
import torch
# isort: on
from parameterized import parameterized
from polygraphy.backend.trt import EngineFromNetwork, TrtRunner

import tensorrt_llm
from tensorrt_llm import Tensor


class TestFunctional(unittest.TestCase):

    def setUp(self):
        tensorrt_llm.logger.set_level('error')

    @parameterized.expand([
        (
            [
                [91, 92, 93, 95, 94, 96, 97, 00,
                 00],  # 7 effective tokens and 2 ignored.
                [93, 94, 95, 92, 95, 96, 93, 97, 96],  # 9 effective tokens
            ],
            [
                [
                    [0, 1, 2, 3],
                    [0, 1, 4, 5],
                    [0, 1, 2, 6],
                ],
                [
                    [0, 1, 2, 3],
                    [0, 4, 5, 6],
                    [0, 1, 7, 8],
                ],
            ],
            [  # Assuming a batch of two sequences, each has 3 beams of 4 tokens.
                [
                    [91, 92, 93, 95],
                    [91, 92, 94, 96],
                    [91, 92, 93, 97],
                ],
                [
                    [93, 94, 95, 92],
                    [93, 95, 96, 93],
                    [93, 94, 97, 96],
                ],
            ],
        ),
        ([[[0, 1], [2, 3]], [[4, 5], [6, 7]]], [[1, 0, 1], [0,
                                                            1, 0]], [[[2, 3],
                                                                      [0, 1],
                                                                      [2, 3]],
                                                                     [[4, 5],
                                                                      [6, 7],
                                                                      [4, 5]]]),
        (
            torch.rand((2, 9, 4), dtype=torch.float32),
            torch.tensor([[[0, 1, 2, 3, 4, 5], [0, 1, 3, 4, 5, 6],
                           [0, 1, 4, 5, 6, 7], [0, 2, 3, 4, 6, 8]],
                          [[0, 1, 2, 3, 4, 5], [0, 1, 3, 4, 5, 7],
                           [0, 2, 3, 5, 6, 7], [0, 3, 4, 5, 6, 7]]]),
            [],
        ),
    ])
    def test_gatherND(self, data, indices, ref):
        data = data if isinstance(data, torch.Tensor) else torch.tensor(data)
        indices = indices if isinstance(indices,
                                        torch.Tensor) else torch.tensor(indices)
        ref = ref if isinstance(ref, torch.Tensor) else torch.tensor(ref)
        indices = indices.unsqueeze(-1)  # needed for TRT gatherND

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            d = Tensor(name='d',
                       shape=data.shape,
                       dtype=tensorrt_llm.torch_dtype_to_trt(data.dtype))
            idx = Tensor(name='idx',
                         shape=indices.shape,
                         dtype=tensorrt_llm.torch_dtype_to_trt(indices.dtype))

            output = tensorrt_llm.functional.gather_nd(d, idx, 1).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork((builder.trt_builder, net.trt_network))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={
                'd': data.numpy(),
                'idx': indices.numpy(),
            })

        # compare diff
        indices = indices.squeeze(-1)
        tref = torch.stack([data[i, indices[i]] for i in range(data.shape[0])])
        if ref.numel() == 0:
            np.testing.assert_allclose(tref, outputs['output'], atol=1e-5)
        else:
            np.testing.assert_allclose(ref, outputs['output'], atol=1e-5)
            np.testing.assert_allclose(ref, tref, atol=1e-5)
        return

    @parameterized.expand([(
        [[91, 92, 93, 95, -1, -1, 94, 96, -1, -1, -1, 97],
         [93, 94, 95, 92, -1, 95, 96, 93, -1, -1, 97, 96]],
        [
            # [0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            # [0, 1, 2, 3, 6, 7, 11, 0, 1, 2, 3, 5, 6, 7, 10, 11]
            [0, 0],
            [0, 1],
            [0, 2],
            [0, 3],
            [0, 6],
            [0, 7],
            [0, 11],
            [1, 0],
            [1, 1],
            [1, 2],
            [1, 3],
            [1, 5],
            [1, 6],
            [1, 7],
            [1, 10],
            [1, 11]
        ],
        [91, 92, 93, 95, 94, 96, 97, 93, 94, 95, 92, 95, 96, 93, 97, 96])])
    def test_gatherND_b0(self, data, indices, ref):
        data = data if isinstance(data, torch.Tensor) else torch.tensor(data)
        indices = indices if isinstance(indices,
                                        torch.Tensor) else torch.tensor(indices)
        ref = ref if isinstance(ref, torch.Tensor) else torch.tensor(ref)
        # indices = indices.unsqueeze(-1) # needed for TRT gatherND

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            d = Tensor(name='d',
                       shape=data.shape,
                       dtype=tensorrt_llm.torch_dtype_to_trt(data.dtype))
            idx = Tensor(name='idx',
                         shape=indices.shape,
                         dtype=tensorrt_llm.torch_dtype_to_trt(indices.dtype))

            output = tensorrt_llm.functional.gather_nd(d, idx, 0).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork((builder.trt_builder, net.trt_network))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={
                'd': data.numpy(),
                'idx': indices.numpy(),
            })

        # compare diff
        # indices = indices.squeeze(-1)
        tref = data[indices[:, 0], indices[:, 1]]
        if ref.numel() == 0:
            np.testing.assert_allclose(tref, outputs['output'], atol=1e-5)
        else:
            np.testing.assert_allclose(ref, outputs['output'], atol=1e-5)
            np.testing.assert_allclose(ref, tref, atol=1e-5)
        return


####

    def test_gatherND_selectH(self):  #, data, indices, ref):
        # This usecase is used to gather in ReDrafter for validated end-tokens ( diff stopping point for diff seqs )
        data = torch.rand((2, 9, 4), dtype=torch.float32)
        indices = torch.randint(9, size=(2, ), dtype=torch.int32)
        ref = []
        data = data if isinstance(data, torch.Tensor) else torch.tensor(data)
        indices = indices if isinstance(indices,
                                        torch.Tensor) else torch.tensor(indices)
        ref = ref if isinstance(ref, torch.Tensor) else torch.tensor(ref)
        indices = torch.stack([torch.arange(2, dtype=torch.int32), indices],
                              dim=1)
        # print(data)
        # print(indices)
        # indices = indices.unsqueeze(-1) # needed for TRT gatherND

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            d = Tensor(name='d',
                       shape=data.shape,
                       dtype=tensorrt_llm.torch_dtype_to_trt(data.dtype))
            idx = Tensor(name='idx',
                         shape=indices.shape,
                         dtype=tensorrt_llm.torch_dtype_to_trt(indices.dtype))

            output = tensorrt_llm.functional.gather_nd(d, idx, 0).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork((builder.trt_builder, net.trt_network))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={
                'd': data.numpy(),
                'idx': indices.numpy(),
            })

        # compare diff
        # indices = indices.squeeze(-1)
        tref = data[indices[:, 0], indices[:, 1]]
        # tref = torch.stack([data[i, indices[i]] for i in range(data.shape[0])])
        if ref.numel() == 0:
            np.testing.assert_allclose(tref, outputs['output'], atol=1e-5)
        else:
            np.testing.assert_allclose(ref, outputs['output'], atol=1e-5)
            np.testing.assert_allclose(ref, tref, atol=1e-5)
        # print(tref.numpy())
        # print(outputs['output'])
        # assert False, "FORCED"
        return
