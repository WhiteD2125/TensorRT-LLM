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

#include "tensorrt_llm/runtime/common.h"
#include "tensorrt_llm/runtime/modelConfig.h"
#include "tensorrt_llm/runtime/worldConfig.h"

#include <filesystem>
#include <istream>
#include <string>
#include <utility>

namespace tensorrt_llm::runtime
{

class GptJsonConfig
{
public:
    GptJsonConfig(std::string name, std::string version, std::string precision, SizeType tensorParallelism,
        SizeType pipelineParallelism, SizeType gpusPerNode, ModelConfig const& modelConfig)
        : mName(std::move(name))
        , mVersion(std::move(version))
        , mPrecision(std::move(precision))
        , mTensorParallelism{tensorParallelism}
        , mPipelineParallelism{pipelineParallelism}
        , mGpusPerNode{gpusPerNode}
        , mModelConfig(modelConfig)
    {
    }

    static GptJsonConfig parse(std::string const& json);

    static GptJsonConfig parse(std::istream& json);

    static GptJsonConfig parse(std::filesystem::path const& path);

    [[nodiscard]] ModelConfig getModelConfig() const
    {
        return mModelConfig;
    }

    [[nodiscard]] std::string const& getName() const
    {
        return mName;
    }

    [[nodiscard]] std::string const& getVersion() const
    {
        return mVersion;
    }

    [[nodiscard]] std::string const& getPrecision() const
    {
        return mPrecision;
    }

    [[nodiscard]] SizeType constexpr getTensorParallelism() const
    {
        return mTensorParallelism;
    }

    [[nodiscard]] SizeType constexpr getPipelineParallelism() const
    {
        return mPipelineParallelism;
    }

    [[nodiscard]] SizeType constexpr getGpusPerNode() const
    {
        return mGpusPerNode;
    }

    [[nodiscard]] SizeType constexpr getWorldSize() const
    {
        return mTensorParallelism * mPipelineParallelism;
    }

    [[nodiscard]] std::string engineFilename(WorldConfig const& worldConfig, std::string const& model) const;

    [[nodiscard]] std::string engineFilename(WorldConfig const& worldConfig) const
    {
        return engineFilename(worldConfig, getName());
    }

private:
    std::string const mName;
    std::string const mVersion;
    std::string const mPrecision;
    SizeType const mTensorParallelism;
    SizeType const mPipelineParallelism;
    SizeType const mGpusPerNode;
    ModelConfig const mModelConfig;
};

} // namespace tensorrt_llm::runtime
