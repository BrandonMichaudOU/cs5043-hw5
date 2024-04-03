#!/bin/bash
#
#SBATCH --partition=debug
#SBATCH --cpus-per-task=16
#SBATCH --mem=1G
#SBATCH --output=outputs/hw5_%j_stdout.txt
#SBATCH --error=outputs/hw5_%j_stderr.txt
#SBATCH --time=00:30:00
#SBATCH --job-name=hw5
#SBATCH --mail-user=brandondmichaud@ou.edu
#SBATCH --mail-type=ALL
#SBATCH --chdir=/home/cs504319/cs5043-hw5

. /home/fagg/tf_setup.sh
conda activate dnn_2024_02


python figure_generator.py