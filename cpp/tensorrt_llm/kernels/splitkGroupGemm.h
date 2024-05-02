/*
 * Copyright (c) 2019-2024, NVIDIA CORPORATION.  All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
#pragma once

#include "cutlass/gemm_coord.h"
#include <NvInferRuntime.h>

namespace tensorrt_llm
{
namespace kernels
{

int64_t getSplitkGroupedGemmParamsWorkSpaceSize(int64_t problem_count);

void splitkGroupedGemm(std::vector<cutlass::gemm::GemmCoord> problem_sizes, std::vector<void*> ptrA,
    std::vector<void*> ptrB, std::vector<void*> ptrC, std::vector<void*> ptrD, void* gemmParamsWorkspace,
    int64_t gemmParamsWorkSpaceSize, void* gemmWorkSpace, int64_t gemmWorkspaceSize,
    std::vector<int64_t> splitkBufferOffsets, bool isLoraIn, nvinfer1::DataType dataType, int splitKSlices,
    cudaStream_t stream);

} // namespace kernels

} // namespace tensorrt_llm
