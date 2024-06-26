#
# SPDX-FileCopyrightText: Copyright (c) 1993-2024 NVIDIA CORPORATION &
# AFFILIATES. All rights reserved. SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.
#

file(GLOB_RECURSE SRC_CPP *.cpp)
file(GLOB_RECURSE SRC_CU *.cu)

# Exclude files in the cutlass_kernels, contextFusedMultiHeadAttention and
# unfusedAttentionKernels folder
list(FILTER SRC_CPP EXCLUDE REGEX "cutlass_kernels/.*")
list(FILTER SRC_CU EXCLUDE REGEX "cutlass_kernels/.*")
list(FILTER SRC_CPP EXCLUDE REGEX "contextFusedMultiHeadAttention/.*")
list(FILTER SRC_CU EXCLUDE REGEX "contextFusedMultiHeadAttention/.*")
list(FILTER SRC_CPP EXCLUDE REGEX "decoderMaskedMultiheadAttention/.*")
list(FILTER SRC_CU EXCLUDE REGEX "decoderMaskedMultiheadAttention/.*")

if(ENABLE_MULTI_DEVICE EQUAL 0)
  list(FILTER SRC_CU EXCLUDE REGEX "customAllReduceKernels*.*cu$")
endif()

add_library(kernels_src STATIC ${SRC_CPP} ${SRC_CU})
set_property(TARGET kernels_src PROPERTY POSITION_INDEPENDENT_CODE ON)
set_property(TARGET kernels_src PROPERTY CUDA_RESOLVE_DEVICE_SYMBOLS ON)

add_subdirectory(cutlass_kernels)
add_subdirectory(decoderMaskedMultiheadAttention)
add_subdirectory(contextFusedMultiHeadAttention)
