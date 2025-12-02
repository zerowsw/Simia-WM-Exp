FROM ubuntu:latest

ENV DEBIAN_FRONTEND=noninteractive


# Install required dependencies
RUN apt-get update && \
    apt-get install -y psmisc bsdmainutils cron && \
    apt-get install -y bash sudo python3 python3-pip && \
    apt-get install -y wget imagemagick dnsutils git tree && \
    apt-get install -y net-tools iputils-ping coreutils && \
    apt-get install -y curl cpio jq vim && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install libreoffice
RUN apt-get update && \
    apt-get install -y libreoffice && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Tessaract
RUN apt-get update && \
    apt-get install -y tesseract-ocr && \
    apt-get install -y libtesseract-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Download and install Miniconda
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh && \
    bash Miniconda3-latest-Linux-x86_64.sh -b -p /opt/conda && \
    rm Miniconda3-latest-Linux-x86_64.sh

# Add Conda to PATH
ENV PATH="/opt/conda/bin:$PATH"

# Activate the Conda environment by default
RUN echo "source /opt/conda/etc/profile.d/conda.sh && conda activate awm" >> ~/.bashrc
ENV PATH="/opt/conda/envs/awm/bin:$PATH"

# Create and activate the Conda environment
RUN conda create -n awm python=3.10

# Install dependencies
COPY ./docker/requirements.txt /
COPY ./docker/setup_py.sh /
RUN chmod +x /setup_py.sh
RUN /bin/bash -c "source ~/.bashrc && source activate awm && sh ./setup_py.sh"
RUN rm /setup_py.sh /requirements.txt

# install azure cli
RUN curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
# Create custom file structure
# COPY ./openai_key.txt /

# Commit custom file system to determine diffs
COPY ./docker/docker.gitignore /
RUN mv docker.gitignore .gitignore
RUN git config --global user.email "office_agent_bench@universityofcalifornia.edu"
RUN git config --global user.name "office_agent_bench@universityofcalifornia.edu"
RUN git init
RUN git add -A
RUN git commit -m 'initial commit'

WORKDIR /
