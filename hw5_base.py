'''
Advanced Machine Learning, 2024
HW 5 Base Code

Author: Andrew H. Fagg (andrewhfagg@gmail.com)

Image classification for the Core 50 data set

Updates for using caching and GPUs
- Batch file:
#SBATCH --gres=gpu:1
#SBATCH --partition=gpu
or
#SBATCH --partition=disc_dual_a100_students
#SBATCH --cpus-per-task=64

- Command line options to include
--cache $LSCRATCH                              (use lscratch to cache the datasets to local fast disk)
--batch 4096                                   (this parameter is per GPU)
--gpu
--precache datasets_by_fold_4_objects          (use a 4-object pre-constructed dataset)

Notes: 
- batch is now a parameter per GPU.  If there are two GPUs, then this number is doubled internally.
   Note that you must do other things to make use of more than one GPU
- 4096 works on the a100 GPUs
- The prcached dataset is a serialized copy of a set of TF.Datasets (located on slow spinning disk).  
Each directory contains all of the images for a single data fold within a couple of files.  Loading 
these files is *a lot* less expensive than having to load the individual images and preprocess them 
at the beginning of a run.
- The cache is used to to store the loaded datasets onto fast, local SSD so they can be fetched quickly
for each training epoch

'''

import sys
import argparse
import pickle
import pandas as pd
import wandb
import socket
import tensorflow as tf

from tensorflow.keras.utils import plot_model
from tensorflow import keras

# Provided
from job_control import *
from pfam_loader import *
from hw5_parser import *

# You need to provide this yourself
from rnn_classifier import *


def exp_type_to_hyperparameters(args):
    '''
    Translate the exp_type into a hyperparameter set

    This is trivial right now

    :param args: ArgumentParser
    :return: Hyperparameter set (in dictionary form)
    '''
    if args.exp_type == 'rnn' or args.expt_type == 'cnn':
        p = {'rotation': range(0, 5)}
    else:
        assert False, "Unrecognized exp_type (%s)" % args.exp_type

    return p


#################################################################
def check_args(args):
    '''
    Check that the input arguments are rational

    '''
    assert (args.spatial_dropout is None or (
            args.spatial_dropout > 0.0 and args.spatial_dropout < 1)), "Spatial dropout must be between 0 and 1"
    assert (args.lrate > 0.0 and args.lrate < 1), "Lrate must be between 0 and 1"
    assert (args.L1_regularization is None or (
            args.L1_regularization > 0.0 and args.L1_regularization < 1)), "L1_regularization must be between 0 and 1"
    assert (args.L2_regularization is None or (
            args.L2_regularization > 0.0 and args.L2_regularization < 1)), "L2_regularization must be between 0 and 1"
    assert (args.cpus_per_task is None or args.cpus_per_task > 1), "cpus_per_task must be positive or None"


def augment_args(args):
    '''
    Use the jobiterator to override the specified arguments based on the experiment index.

    Modifies the args

    :param args: arguments from ArgumentParser
    :return: A string representing the selection of parameters to be used in the file name
    '''

    # Create parameter sets to execute the experiment on.  This defines the Cartesian product
    #  of experiments that we will be executing
    p = exp_type_to_hyperparameters(args)

    # Check index number
    index = args.exp_index
    if index is None:
        return ""

    # Create the iterator
    ji = JobIterator(p)
    print("Total jobs:", ji.get_njobs())

    # Check bounds
    assert (args.exp_index >= 0 and args.exp_index < ji.get_njobs()), "exp_index out of range"

    # Print the parameters specific to this exp_index
    print(ji.get_index(args.exp_index))

    # Push the attributes to the args object and return a string that describes these structures
    return ji.set_attributes_by_index(args.exp_index, args)


#################################################################

def generate_fname(args, params_str):
    '''
    Generate the base file name for output files/directories.
    
    The approach is to encode the key experimental parameters in the file name.  This
    way, they are unique and easy to identify after the fact.

    :param args: from argParse
    :params_str: String generated by the JobIterator
    '''
    # # Spatial Dropout
    # if args.spatial_dropout is None:
    #     sdropout_str = ''
    # else:
    #     sdropout_str = 'sdrop_%0.3f_' % (args.spatial_dropout)
    #
    # # L1 regularization
    # if args.L1_regularization is None:
    #     regularizer_l1_str = ''
    # else:
    #     regularizer_l1_str = 'L1_%0.6f_' % (args.L1_regularization)
    #
    # # L2 regularization
    # if args.L2_regularization is None:
    #     regularizer_l2_str = ''
    # else:
    #     regularizer_l2_str = 'L2_%0.6f_' % (args.L2_regularization)
    #
    # # Label
    # if args.label is None:
    #     label_str = ""
    # else:
    #     label_str = "%s_" % args.label
    #
    # # Experiment type
    # if args.exp_type is None:
    #     experiment_type_str = ""
    # else:
    #     experiment_type_str = "%s_" % args.exp_type
    #
    # # learning rate
    # lrate_str = "LR_%0.6f_" % args.lrate
    #
    # # Put it all together, including #of training folds and the experiment rotation
    # return "%s/image_%s%sCsize_%02d_Pool_%02d_Pad_%s_%s%s%s%sfold_%02d_depth_%d" % (
    #     args.results_path,
    #     experiment_type_str,
    #     label_str,
    #     args.conv_size,
    #     args.pool,
    #     args.padding,
    #     sdropout_str,
    #     regularizer_l1_str,
    #     regularizer_l2_str,
    #     lrate_str,
    #     args.fold,
    #     args.depth)

    return f'{args.results_path}/{args.exp_type}'


def create_classifier_network(args, n_classes):
    if args.exp_type == 'rnn':
        return create_simple_rnn(args.rnn_layers,
                                 args.dense_layers,
                                 n_classes,
                                 activation_rnn=args.rnn_activation,
                                 activation_dense=args.dense_activation,
                                 return_sequences=args.return_sequences,
                                 unroll=args.unroll,
                                 lambda_regularization=args.L2_regularization,
                                 dropout=args.dropout,
                                 batch_normalization=args.batch_normalization,
                                 grad_clip=args.grad_clip,
                                 lrate=args.lrate,
                                 loss=tf.keras.losses.SparseCategoricalCrossentropy(),
                                 metrics=[tf.keras.metrics.SparseCategoricalAccuracy()])
    elif args.exp_type == 'cnn':
        return None
    else:
        assert False, f'unrecognized experiment type {args.exp_type}'


def execute_exp(args=None, multi_gpus=False):
    '''
    Perform the training and evaluation for a single model
    
    :param args: Argparse arguments
    :param multi_gpus: True if there are more than one GPU
    '''

    # Check the arguments
    if args is None:
        # Case where no args are given (usually, because we are calling from within Jupyter)
        #  In this situation, we just use the default arguments
        parser = create_parser()
        args = parser.parse_args([])

    print(args.exp_index)

    # Override arguments if we are using exp_index
    args_str = augment_args(args)

    # Scale the batch size with the number of GPUs
    if multi_gpus > 1:
        args.batch = args.batch * multi_gpus

    print('Batch size', args.batch)

    ####################################################
    # Create the TF datasets for training, validation, testing

    if args.verbose >= 3:
        print('Starting data flow')

    # Load individual files (all objects)
    data_set_dict = load_rotation(basedir=args.dataset,
                                  rotation=args.rotation)
    n_tokens = data_set_dict['n_tokens']
    n_classes = data_set_dict['n_classes']
    ds_train, ds_validation, ds_testing = create_tf_datasets(dat=data_set_dict,
                                                             batch=args.batch,
                                                             prefetch=args.prefetch,
                                                             shuffle=args.shuffle,
                                                             repeat=args.repeat,
                                                             cache=args.cache)

    # Build the model
    if args.verbose >= 3:
        print('Building network')

    # Create the network
    if multi_gpus > 1:
        # Multiple GPUs
        mirrored_strategy = tf.distribute.MirroredStrategy()

        with mirrored_strategy.scope():
            # Build network: you must provide your own implementation
            model = create_classifier_network(args, n_classes)
    else:
        # Single GPU
        # Build network: you must provide your own implementation
        model = create_classifier_network(args, n_classes)

    # Report model structure if verbosity is turned on
    if args.verbose >= 1:
        print(model.summary())

    print(args)

    # Output file base and pkl file
    fbase = generate_fname(args, args_str)
    print(fbase)
    fname_out = "%s_results.pkl" % fbase

    # Plot the model
    if args.render:
        render_fname = '%s_model_plot.png' % fbase
        plot_model(model, to_file=render_fname, show_shapes=True, show_layer_names=True)

    # Perform the experiment?
    if args.nogo:
        # No!
        print("NO GO")
        print(fbase)
        return

    # Check if output file already exists
    if not args.force and os.path.exists(fname_out):
        # Results file does exist: exit
        print("File %s already exists" % fname_out)
        return

    #####
    # Start wandb
    run = wandb.init(project=args.project, name='%s_F%d' % (args.label, args.fold), notes=fbase, config=vars(args))

    # Log hostname
    wandb.log({'hostname': socket.gethostname()})

    # Log model design image
    if args.render:
        wandb.log({'model architecture': wandb.Image(render_fname)})

    # Callbacks
    cbs = []
    early_stopping_cb = keras.callbacks.EarlyStopping(patience=args.patience, restore_best_weights=True,
                                                      min_delta=args.min_delta, monitor=args.monitor)
    cbs.append(early_stopping_cb)

    # Weights and Biases
    wandb_metrics_cb = wandb.keras.WandbMetricsLogger()
    cbs.append(wandb_metrics_cb)

    if args.verbose >= 3:
        print('Fitting model')

    # Learn
    history = model.fit(ds_train,
                        epochs=args.epochs,
                        steps_per_epoch=args.steps_per_epoch,
                        use_multiprocessing=True,
                        verbose=args.verbose >= 2,
                        validation_data=ds_validation,
                        validation_steps=None,
                        callbacks=cbs)

    # Done training

    # Generate results data
    results = {}

    # Test set
    if ds_testing is not None:
        print('#################')
        print('Testing')
        results['predict_testing_eval'] = model.evaluate(ds_testing)
        wandb.log({'final_test_loss': results['predict_testing_eval'][0]})
        wandb.log({'final_test_sparse_categorical_accuracy': results['predict_testing_eval'][1]})

    # Save results
    fbase = generate_fname(args, args_str)
    results['fname_base'] = fbase
    with open("%s_results.pkl" % (fbase), "wb") as fp:
        pickle.dump(results, fp)

    # Save model
    if args.save_model:
        model.save("%s_model" % (fbase))

    wandb.finish()

    return model


def check_completeness(args):
    '''
    Check the completeness of a Cartesian product run.

    All other args should be the same as if you executed your batch, however, the '--check' flag has been set

    Prints a report of the missing runs, including both the exp_index and the name of the missing results file

    :param args: ArgumentParser

    '''

    # Get the corresponding hyperparameters
    p = exp_type_to_hyperparameters(args)

    # Create the iterator
    ji = JobIterator(p)

    print("Total jobs: %d" % ji.get_njobs())

    print("MISSING RUNS:")

    indices = []
    # Iterate over all possible jobs
    for i in range(ji.get_njobs()):
        params_str = ji.set_attributes_by_index(i, args)
        # Compute output file name base
        fbase = generate_fname(args, params_str)

        # Output pickle file name
        fname_out = "%s_results.pkl" % (fbase)

        if not os.path.exists(fname_out):
            # Results file does not exist: report it
            print("%3d\t%s" % (i, fname_out))
            indices.append(i)

    # Give the list of indices that can be inserted into the --array line of the batch file
    print("Missing indices (%d): %s" % (len(indices), ','.join(str(x) for x in indices)))


if __name__ == "__main__":
    # Parse and check incoming arguments
    parser = create_parser()
    args = parser.parse_args()
    check_args(args)

    # n_physical_devices = 0

    if args.verbose >= 3:
        print('Arguments parsed')

    # Turn off GPU?
    if not args.gpu or "CUDA_VISIBLE_DEVICES" not in os.environ.keys():
        tf.config.set_visible_devices([], 'GPU')
        print('NO VISIBLE DEVICES!!!!')

    # GPU check
    visible_devices = tf.config.get_visible_devices('GPU')
    n_visible_devices = len(visible_devices)
    print('GPUS:', visible_devices)
    if n_visible_devices > 0:
        for device in visible_devices:
            tf.config.experimental.set_memory_growth(device, True)
        print('We have %d GPUs\n' % n_visible_devices)
    else:
        print('NO GPU')

    if args.check:
        # Just check to see if all experiments have been executed
        check_completeness(args)
    else:
        # Execute the experiment

        # Set number of threads, if it is specified
        if args.cpus_per_task is not None:
            tf.config.threading.set_intra_op_parallelism_threads(args.cpus_per_task)
            tf.config.threading.set_inter_op_parallelism_threads(args.cpus_per_task)

        execute_exp(args, multi_gpus=n_visible_devices)
