/*
 * Copyright (c) 2022-2024, NVIDIA CORPORATION.  All rights reserved.
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

#include "tensorrt_llm/executor/types.h"

namespace tensorrt_llm::batch_manager::batch_scheduler
{

enum class SchedulerPolicy
{
    MAX_UTILIZATION,
    GUARANTEED_NO_EVICT,
};

SchedulerPolicy execToBatchManagerSchedPolicy(executor::SchedulerPolicy policy);

executor::SchedulerPolicy batchManagerToExecSchedPolicy(SchedulerPolicy policy);

std::ostream& operator<<(std::ostream& os, SchedulerPolicy policy);

} // namespace tensorrt_llm::batch_manager::batch_scheduler
