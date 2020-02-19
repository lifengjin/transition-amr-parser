set -o errexit 
set -o pipefail
# setup environment
. set_environment.sh
# Argument handling
config=$1
checkpoint=$2
[ -z "$config" ] && \
    echo -e "\ntest.sh <config> <model_checkpoint>\n" && \
    exit 1
[ -z "$checkpoint" ] && \
    echo -e "\ntest.sh <config> <model_checkpoint>\n" && \
    exit 1
set -o nounset 

# Load config
. "$config"

results_folder=$(dirname $checkpoint)/$TEST_TAG/

mkdir -p $results_folder

# decode 
echo "fairseq-generate $FAIRSEQ_GENERATE_ARGS --path $checkpoint --results-path $results_folder"
fairseq-generate $FAIRSEQ_GENERATE_ARGS \
    --path $checkpoint \
    --results-path $results_folder
# to profile decoder
# 1. pip install line_profiler
# 2. decorate target function with @profile
# 3. call instead of fairseq-generate
# kernprof -l generate.py $fairseq_generate_args --path $checkpoint
# 4. then you can consult details with 
# python -m line_profiler generate.py.lprof

model_folder=$(dirname $checkpoint)

# Create the AMR from the model obtained actions
amr-fake-parse \
    --in-sentences $ORACLE_FOLDER/dev.en \
    --in-actions $results_folder/valid.actions \
    --out-amr $results_folder/valid.amr \

# Compute score
smatch.py \
     --significant 4  \
     -f $AMR_DEV_FILE \
     $results_folder/valid.amr \
     -r 10 \
     > $results_folder/valid.smatch

# show Smatch results
cat $results_folder/valid.smatch
