from __future__ import division
from __future__ import print_function

import time
import os
import tensorflow as tf

from utils import *
from metrics import *
from models import GCN_Align

# Set random seed
seed = 12306
np.random.seed(seed)
tf.set_random_seed(seed)

# Settings
flags = tf.app.flags
FLAGS = flags.FLAGS
flags.DEFINE_string('lang', 'zh_en', 'Dataset string.')  # 'zh_en', 'ja_en', 'fr_en'
flags.DEFINE_float('learning_rate', 20, 'Initial learning rate.')
flags.DEFINE_integer('epochs', 2000, 'Number of epochs to train.')
flags.DEFINE_float('dropout', 0., 'Dropout rate (1 - keep probability).')
flags.DEFINE_float('gamma', 3.0, 'Hyper-parameter for margin based loss.')
flags.DEFINE_integer('k', 5, 'Number of negative samples for each positive seed.')
flags.DEFINE_float('beta', 0.9, 'Weight for structure embeddings.(SE+AE)')
flags.DEFINE_float('beta3', 0.7, 'Weight for structure embeddings.(GCN+TransE)')
flags.DEFINE_integer('se_dim', 200, 'Dimension for SE.')
flags.DEFINE_integer('ae_dim', 100, 'Dimension for AE.')
flags.DEFINE_integer('seed', 3, 'Proportion of seeds, 3 means 30%')
flags.DEFINE_float('weight_decay', 1e-5, 'Weight for L2 loss on embedding matrix.')

# TransE params
gcn_data_path = 'data/' + FLAGS.lang + '/'
gcn_data_converted_path = 'data/' + FLAGS.lang + '/for_jape/'
jape_results = gcn_data_converted_path + ('0_' + str(FLAGS.seed)) + '/jape_ent_embeddings.npy'
jape_results_converted = gcn_data_converted_path + ('0_' + str(FLAGS.seed)) + '/jape_ent_embeddings_converted.npy'

# Load data
adj, ae_input, train, test, ent2id_div, KG = load_data(FLAGS.lang)

# TransE vec
print("prepare data for jape...")
mp1, mp2 = gcn_data_to_jape(train, test, ent2id_div[0], ent2id_div[1],
                            KG[0], KG[1], '0.' + str(FLAGS.seed),
                            gcn_data_converted_path)
print("running jape_se...")
if not os.path.exists(jape_results):
    runJAPE = os.system('python3 jape_code/se_pos_neg.py ' + gcn_data_converted_path + ' 0.' + str(FLAGS.seed))
    if runJAPE == 0:
        print('jape finished.')
    else:
        print('some errors occur when co-training.')
jape_results_to_gcn(mp1, mp2, np.load(jape_results), jape_results_converted)
print("return jape results finished.")
TransE_vec = np.load(jape_results_converted)
print('shape of TransE embedding:', TransE_vec.shape)
# print('TransE')
# get_hits(TransE_vec, test)

# Some preprocessing
support = [preprocess_adj(adj)]
num_supports = 1
model_func = GCN_Align
k = FLAGS.k
e = ae_input[2][0]

# Define placeholders
ph_ae = {
    'support': [tf.sparse_placeholder(tf.float32) for _ in range(num_supports)],
    'features': tf.sparse_placeholder(tf.float32), #tf.placeholder(tf.float32),
    'dropout': tf.placeholder_with_default(0., shape=()),
    'num_features_nonzero': tf.placeholder_with_default(0, shape=())
}
ph_se = {
    'support': [tf.sparse_placeholder(tf.float32) for _ in range(num_supports)],
    'features': tf.placeholder(tf.float32),
    'dropout': tf.placeholder_with_default(0., shape=()),
    'num_features_nonzero': tf.placeholder_with_default(0, shape=())
}

# Create model
model_ae = model_func(ph_ae, input_dim=ae_input[2][1], output_dim=FLAGS.ae_dim, ILL=train, sparse_inputs=True, featureless=False, decay=True, logging=True)
model_se = model_func(ph_se, input_dim=e, output_dim=FLAGS.se_dim, ILL=train, sparse_inputs=False, featureless=True, decay=False, logging=True)
# Initialize session
sess = tf.Session()

# Init variables
sess.run(tf.global_variables_initializer())

cost_val = []

t = len(train)
L = np.ones((t, k)) * (train[:, 0].reshape((t, 1)))
neg_left = L.reshape((t * k,))
L = np.ones((t, k)) * (train[:, 1].reshape((t, 1)))
neg2_right = L.reshape((t * k,))

# Train model
for epoch in range(FLAGS.epochs):
    if epoch % 10 == 0:
        neg2_left = np.random.choice(e, t * k)
        neg_right = np.random.choice(e, t * k)
    # Construct feed dictionary
    feed_dict_ae = construct_feed_dict(ae_input, support, ph_ae)
    feed_dict_ae.update({ph_ae['dropout']: FLAGS.dropout})
    feed_dict_ae.update({'neg_left:0': neg_left, 'neg_right:0': neg_right, 'neg2_left:0': neg2_left, 'neg2_right:0': neg2_right})
    feed_dict_se = construct_feed_dict(1.0, support, ph_se)
    feed_dict_se.update({ph_se['dropout']: FLAGS.dropout})
    feed_dict_se.update({'neg_left:0': neg_left, 'neg_right:0': neg_right, 'neg2_left:0': neg2_left, 'neg2_right:0': neg2_right})
    # Training step
    outs_ae = sess.run([model_ae.opt_op, model_ae.loss], feed_dict=feed_dict_ae)
    outs_se = sess.run([model_se.opt_op, model_se.loss], feed_dict=feed_dict_se)
    cost_val.append((outs_ae[1], outs_se[1]))

    # Print results
    print("Epoch:", '%04d' % (epoch + 1), "AE_train_loss=", "{:.5f}".format(outs_ae[1]), "SE_train_loss=", "{:.5f}".format(outs_se[1]))

print("Optimization Finished!")

# Testing
feed_dict_ae = construct_feed_dict(ae_input, support, ph_ae)
feed_dict_se = construct_feed_dict(1.0, support, ph_se)
vec_ae = sess.run(model_ae.outputs, feed_dict=feed_dict_ae)
vec_se = sess.run(model_se.outputs, feed_dict=feed_dict_se)

# print("AE")
# get_hits(vec_ae, test)
#print("SE")
#get_hits(vec_se, test)
#print("SE+AE")
#GCN_vec = get_combine_hits(vec_se, vec_ae, FLAGS.beta, test)
#print('Result of GCN+TransE')
#EMB_vec = get_combine_hits(GCN_vec, TransE_vec, FLAGS.beta3, test)

#GCN_vec = np.concatenate([0.9*vec_se, 0.1*vec_ae], axis=1)


tf.reset_default_graph()

weight = tf.nn.softmax(tf.Variable(tf.zeros(3)))



opt = tf.train.GradientDescentOptimizer(learning_rate=1)

se_vec = tf.constant(vec_se)
ae_vec = tf.constant(vec_ae)
TransE_vec = tf.constant(TransE_vec)

emb = tf.concat([se_vec*weight[0], ae_vec*weight[1], TransE_vec*weight[2]], axis=1)
loss = align_loss(emb, train, FLAGS.gamma, FLAGS.k)
opt_op = opt.minimize(loss)

# Initialize session
sess = tf.Session()

# Init variables
sess.run(tf.global_variables_initializer())

for epoch in range(1000):
    if epoch % 10 == 0:
        neg2_left = np.random.choice(e, t * k)
        neg_right = np.random.choice(e, t * k)
    # Construct feed dictionary
    feed_dict = {}
    feed_dict.update({'neg_left:0': neg_left, 'neg_right:0': neg_right, 'neg2_left:0': neg2_left, 'neg2_right:0': neg2_right})
    _, th = sess.run([opt_op, loss], feed_dict=feed_dict)
    print(th)

embedding = sess.run(emb)
print(sess.run(weight))
get_hits(embedding, test)
