FROM nvidia/cuda:12.4.0-devel-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    vim \
    sudo \
    tmux \
    unzip \
    openssh-server \
    openssh-client \
    build-essential \
    software-properties-common \
    tesseract-ocr \
    poppler-utils \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI (gh)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.12 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# Create ray user (required by Ray cluster)
RUN useradd -ms /bin/bash ray \
    && echo "ray ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Install pip for Python 3.12
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

# Set working directory
WORKDIR /workspace

# Clone the repository
ARG REPO_URL=https://github.com/zerowsw/Simia-WM-Exp.git
ARG BRANCH=main
RUN git clone --branch ${BRANCH} ${REPO_URL} /workspace/Simia-WM-Exp

WORKDIR /workspace/Simia-WM-Exp

# Install PyTorch with CUDA support
RUN pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124

# Install vLLM
RUN pip install --no-cache-dir vllm==0.8.5

# Install flash-attention (requires CUDA)
RUN pip cache purge && \
    pip install --no-cache-dir flash-attn==2.7.4.post1 --no-build-isolation

# Install verl and ragen in editable mode
RUN pip install --no-cache-dir -e Simia-RL/subtrees/verl -e Simia-RL/subtrees/ragen --no-dependencies

# Install ragen requirements (without webshop external dependencies)
RUN pip install --no-cache-dir \
    IPython \
    matplotlib \
    gym \
    gym-sokoban \
    peft \
    accelerate \
    codetiming \
    datasets \
    dill \
    hydra-core \
    "numpy<2.3" \
    pandas \
    pybind11 \
    "ray[default]>=2.10" \
    tensordict==0.6.2 \
    transformers \
    wandb \
    gymnasium \
    "gymnasium[toy-text]" \
    "pyarrow>=15.0.0" \
    pylatexenc \
    torchdata \
    debugpy \
    together \
    anthropic \
    liger-kernel

# Install remaining requirements for Simia-RL
RUN pip install --no-cache-dir \
    fire \
    python-docx \
    scikit-learn \
    openpyxl \
    tabulate \
    Pillow \
    PyMuPDF \
    PyPDF2 \
    pdf2docx \
    pytesseract \
    icalendar \
    gymnasium \
    rich \
    docker \
    mysql-connector-python \
    rpyc \
    pyyaml \
    msal \
    "ruamel.yaml==0.18.10"

# Install additional dependencies for MLflow and Azure
RUN pip install --no-cache-dir --ignore-installed azureml-mlflow mlflow

# Install specific versions of ray (opentelemetry will be installed as dependency)
RUN pip install --no-cache-dir "ray[default]==2.49.1"

# Install LLaMA Factory for SFT training (neat_packing incompatible with transformers>=4.53.0)
RUN pip install --no-cache-dir llamafactory && \
    pip install --no-cache-dir "transformers>=4.40,<4.53"

# Install DeepSpeed for memory-efficient distributed training (ZeRO)
RUN pip install --no-cache-dir "deepspeed>=0.10.0,<=0.16.9"

# Install OpenAI SDK for API interactions
RUN pip install --no-cache-dir openai

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code || \
    (curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
     apt-get install -y nodejs && \
     npm install -g @anthropic-ai/claude-code)

# Re-pin numpy (later installs like mlflow/ray/llamafactory can upgrade it)
RUN pip install --no-cache-dir "numpy<2.3"

# Unzip preprocessed data files
RUN cd Simia_SFT/Tau2 && unzip -o APIGen_5k_preprocessed_zip.zip || true
RUN cd Simia-RL && unzip -o APIGen_5k_processed_zip.zip || true

# Set default environment variables (users should override these)
ENV API_TYPE="openai"
ENV OPENAI_API_KEY=""
ENV AZURE_OPENAI_ENDPOINT=""
ENV WANDB_API_KEY=""
