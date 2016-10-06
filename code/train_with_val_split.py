# Written by: Erick Cobos T.
# Date: October 2016
""" Trains the convolutional network with the provided data.

	If defined, uses VAL_CSV_PATH as the validation set; otherwise, splits the 
	training set in training and validation.

	Example:
		python3 train.py
"""
import numpy as np
import model_v4.py as model
import tensorflow as tf
import os
import random

# Set training parameters
TRAINING_STEPS = 163*8*5 # 163 mammograms (approx) * 8 augmentations * 5 epochs
LEARNING_RATE = 4e-5
LAMBDA = 4e-4
RESUME_TRAINING = False

# Set some path
DATA_DIR = "data" # folder with training data (images and labels)
MODEL_DIR = "run116" # folder to store model checkpoints and summary files
CSV_PATH = "training.csv" # path to csv file with image and label filenames
VAL_CSV_PATH = None # path to validation set. If undefined, split training set
NUM_VAL_PATIENTS = 10 # number of patients for validation set; used only if 
					  # val_csv is not provided

def read_csv_info(csv_path):
	""" Reads the csv file and returns two lists: one with image filenames and 
	one with label filenames."""
	filenames = np.loadtxt(csv_path, dtype=bytes, delimiter=',').astype(str)
	
	return list(filenames[:, 0]), list(filenames[:, 1])
	
def create_filename_queue(image_filenames, label_filenames):
	""" Creates a shuffling queue with (image, label) filename pairs."""
	with tf.name_scope('filename_queue'):
		# Transform input to tensors
		image_filenames = tf.convert_to_tensor(image_filenames)
		label_filenames = tf.convert_to_tensor(label_filenames)
		
		# Create never-ending shuffling queue of filenames
		filename_queue = tf.train.slice_input_producer([image_filenames, 
														label_filenames])
	return filename_queue
	
def val_split(csv_path, num_val_patients, model_dir):
	""" Divides the data set into training and validation set sampling 
	num_val_patients patients at random."""
	# Read csv file
	with open(csv_path) as csv_file:
		lines = csv_file.read().splitlines()

	# Get patients at random
	val_patients = {}
	while len(val_patients) < num_val_patients:
		patient_name = random.choice(lines).split('/')[0]
		val_patients.add(patient_name)

	# Divide val and training set
	val_lines = [line for line in lines if line.split('/')[0] in val_patients]
	training_lines = [l for l in lines if l.split('/')[0] not in val_patients]
	
	# Write training and val csvs to disk
	with open(model_dir + os.path.sep + 'val.csv') as val_file:
		val_file.write('\n'.join(val_lines))
	with open(model_dir + os.path.sep + 'training.csv') as training_file:
		training_file.write('\n'.join(training_lines))
			
	# Generate lists of filenames
	training_image_filenames = [line.split(',')[0] for line in training_lines]
	training_label_filenames = [line.split(',')[1] for line in training_lines]
	val_image_filenames = [line.split(',')[0] for line in val_lines]
	val_label_filenames = [line.split(',')[1] for line in val_lines]
	
	return training_image_filenames, training_label_filenames, 
		   val_image_filenames, val_label_filenames

def preprocess_example(image_filename, label_filename, data_dir):
	""" Loads an image (and its label) and augments it.
	
	Args:
		csv_path: A string. Path to csv file with image and label filenames.
			Each record is expected to be in the form:
			'image_filename,label_filename'
		data_dir: A string. Path to the data directory. Default is "."
		capacity: An integer. Maximum amount of examples that may be stored in 
			the example queue. Default is 5.
		name: A string. Name for the produced examples. Default is 'new_example'
	
	Returns:
		An (image, label) tuple where image is a tensor of floats with shape
		[image_height, image_width, image_channels] and label is a tensor of
		integers with shape [image_height, image_width]
	"""
	with tf.name_scope('decode_image'):
		# Load image
		image_path = data_dir + os.path.sep + image_filename
		image_content = tf.read_file(image_path)
		image = tf.image.decode_png(image_content)
		
		# Load label image
		label_path = data_dir + os.path.sep + label_filename
		label_content = tf.read_file(label_path)
		label = tf.image.decode_png(label_content)
		
	with tf.name_scope('augment_image'):
		# Mirror the image (horizontal flip) with 0.5 chance
		flip_prob = tf.random_uniform([])
		flipped_image = tf.cond(tf.less(flip_prob, 0.5), lambda: image,
								lambda: tf.image.flip_left_right(image))
		flipped_label = tf.cond(tf.less(flip_prob, 0.5), lambda: label,
								lambda: tf.image.flip_left_right(label))
										
		# Rotate image at 0, 90, 180 or 270 degrees
		number_of_rot90s = tf.random_uniform([], maxval=4, dtype=tf.int32)
		rotated_image = tf.image.rot90(flipped_image, number_of_rot90s)
		rotated_label = tf.image.rot90(flipped_label, number_of_rot90s)
		
	with tf.name_scope('whiten_image'):		
		# Whiten the image (zero-center and unit variance)
		whitened_image = tf.image.per_image_whitening(rotated_image)
		whitened_label = tf.squeeze(rotated_label) # not whiten, just unwrap it
				
	return whitened_image, whitened_label

def log(*messages):
	""" Simple logging function."""
	formatted_time = "[{}]".format(time.ctime())
	print(formatted_time, *messages)
		
def train(training_steps = TRAINING_STEPS, learning_rate=LEARNING_RATE, 
		 lambda_=LAMBDA, resume_training=RESUME_TRAINING, csv_path=CSV_PATH, 
		 model_dir=MODEL_DIR, val_csv_path=VAL_CSV_PATH, 
		 num_val_patients = NUM_VAL_PATIENTS):
	""" Reads training info and trains a convolutional network."""
	# Read csv file(s) with training info
	if val_csv_path:
		training_images, training_labels = read_csv_info(csv_path)
		val_images, val_labels = read_csv_info(val_csv_path) 
	else:
		training_images, training_labels, val_images, val_labels = val_split(
										  csv_path, num_val_patients, model_dir)
	
	# Create a never-ending shuffling queue of filenames
	training_filenames = create_filename_queue(training_images, training_labels)
	val_filenames = create_filename_queue(val_images, val_labels)
	
	# Variables that change between runs: need to be feeded to the graph
	image_filename = tf.placeholder(tf.string, name='image_filename')
	label_filename = tf.placeholder(tf.string, name='label_filename')
	drop = tf.placeholder(tf.bool, shape=(), name='drop') # Dropout? (T/F)
	
	# Read and augment image
	image, label = preprocess_example(image_filename, label_filename, data_dir)

	# Define the model
	prediction = model.forward(image, drop)
	
	# Compute the loss
	logistic_loss = model.loss(prediction, label)
	loss = logistic_loss + lambda_ * model.regularization_loss()
		
	# Set an optimizer
	train_op, global_step = update_weights(loss, learning_rate)
	
	# Get a summary writer
	if not os.path.exists(model_dir): os.makedirs(model_dir)
	summary_writer = tf.train.SummaryWriter(model_dir)
	summaries = tf.merge_all_summaries()
	
	# Get a saver (for checkpoints)
	saver = tf.train.Saver()

	# Use CPU-only. To enable GPU, delete this and call with tf.Session() as ...
	config = tf.ConfigProto(device_count={'GPU':0})
	
	# Launch graph
	with tf.Session(config=config) as sess:
		# Initialize variables
		if restore_variables:
			checkpoint_path = tf.train.latest_checkpoint(checkpoint_dir)
			log("Restoring model from:", checkpoint_path)
			saver.restore(sess, checkpoint_path)	
		else:
			tf.initialize_all_variables().run()
			summary_writer.add_graph(sess.graph)
		
		# Start queue runners
		queue_runners = tf.train.start_queue_runners()
				
		# Initial log
		step = global_step.eval()
		log("Starting training @", step)
		
		# Training loop
		for i in range(training_steps):
			# Train
			training_filename = training_filenames.dequeue().run()
			feed_dict = {image_filename: training_filename[0], 
						 label_filename: training_filename[1], drop: True}
			train_logistic_loss, train_loss, _ = sess.run([logistic_loss, loss,
														   train_op], feed_dict)
			step += 1
			
			# Report losses (calculated before the training step)
			loss_summary = tf.scalar_summary(['training/logistic_loss', 
											  'training/loss'],
								 			 [train_logistic_loss, train_loss], 
								 			 collections=[])
			summary_writer.add_summary(loss_summary, step - 1)
			log("Training loss @", step - 1, ":", train_logistic_loss,
				"(logistic)", train_loss, "(total)")
			
			# Write summaries
			if step%50 == 0 or step == 1:
				summary_str = summaries.eval(feed_dict)
				summary_writer.add_summary(summary_str, step)
				log("Summaries written @", step)
			
			# Evaluate model
			if step%100 == 0 or step == 1:
				log("Evaluating model")
				
				# Average loss over 5 val images
				val_loss = 0
				number_of_images = 5
				for j in range(number_of_images):
					val_filename = val_filenames.dequeue().run()
					feed_dict ={image_filename: val_filename[0], 
								label_filename: val_filename[1], drop: False}
					one_loss = logistic_loss.eval(feed_dict)
					val_loss += (one_loss / number_of_images)

				# Report validation loss	
				loss_summary = tf.scalar_summary('val/logistic_loss', val_loss, 
												 collections=[])
				summary_writer.add_summary(loss_summary, step)
				log("Validation loss @", step, ":", val_loss)
			
			# Write checkpoint	
			if step%250 == 0 or i == (training_steps - 1):
				checkpoint_name = os.path.join(model_dir, 'chkpt')
				checkpoint_path = saver.save(sess, checkpoint_name, step)
				log("Checkpoint saved in:", checkpoint_path)
			
		# Final log
		log("Done!")
		
	# Flush and close the summary writer
	summary_writer.close()

# Trains a model from scratch
if __name__ == "__main__":
	train()