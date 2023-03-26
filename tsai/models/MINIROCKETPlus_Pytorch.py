# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/057_models.MINIROCKETPlus_Pytorch.ipynb.

# %% auto 0
__all__ = ['MiniRocketFeaturesPlus', 'Flatten', 'MiniRocketPlus', 'get_minirocket_features', 'MiniRocketHead',
           'InceptionRocketFeaturesPlus', 'InceptionRocketPlus']

# %% ../../nbs/057_models.MINIROCKETPlus_Pytorch.ipynb 3
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import math
from collections import OrderedDict
import itertools

# %% ../../nbs/057_models.MINIROCKETPlus_Pytorch.ipynb 4
class MiniRocketFeaturesPlus(nn.Module):
    fitting = False

    def __init__(self, c_in, seq_len, num_features=10_000, max_dilations_per_kernel=32, kernel_size=9, max_num_channels=9, max_num_kernels=84,
                 add_lsaz=False):
        super(MiniRocketFeaturesPlus, self).__init__()
        self.c_in, self.seq_len = c_in, seq_len
        self.kernel_size, self.max_num_channels, self.add_lsaz = kernel_size, max_num_channels, add_lsaz

        # Kernels
        indices, pos_values = self.get_indices(kernel_size, max_num_kernels)
        self.num_kernels = len(indices)
        kernels = (-torch.ones(self.num_kernels, 1, self.kernel_size)).scatter_(2, indices, pos_values)
        self.indices = indices
        self.kernels = nn.Parameter(kernels.repeat(c_in, 1, 1), requires_grad=False)
        if add_lsaz:
            num_features = num_features // 2
        self.num_features = num_features // self.num_kernels * self.num_kernels
        self.max_dilations_per_kernel = max_dilations_per_kernel

        # Dilations
        self.set_dilations(seq_len)

        # Channel combinations (multivariate)
        if c_in > 1:
            self.set_channel_combinations(c_in, max_num_channels)

        # Bias
        for i in range(self.num_dilations):
            self.register_buffer(f'biases_{i}', torch.empty(
                (self.num_kernels, self.num_features_per_dilation[i])))
        self.register_buffer('prefit', torch.BoolTensor([False]))

    def forward(self, x):
        _features = []
        for i, (dilation, padding) in enumerate(zip(self.dilations, self.padding)):
            _padding1 = i % 2

            # Convolution
            C = F.conv1d(x, self.kernels, padding=padding,
                         dilation=dilation, groups=self.c_in)
            if self.c_in > 1:  # multivariate
                C = C.reshape(x.shape[0], self.c_in, self.num_kernels, -1)
                channel_combination = getattr(
                    self, f'channel_combinations_{i}')
                C = torch.mul(C, channel_combination)
                C = C.sum(1)

            # Bias
            if not self.prefit or self.fitting:
                num_features_this_dilation = self.num_features_per_dilation[i]
                bias_this_dilation = self.get_bias(
                    C, num_features_this_dilation)
                setattr(self, f'biases_{i}', bias_this_dilation)
                if self.fitting:
                    if i < self.num_dilations - 1:
                        continue
                    else:
                        self.prefit = torch.BoolTensor([True])
                        return
                elif i == self.num_dilations - 1:
                    self.prefit = torch.BoolTensor([True])
            else:
                bias_this_dilation = getattr(self, f'biases_{i}')

            # Features
            _features.append(self.get_PPVs(
                C[:, _padding1::2], bias_this_dilation[_padding1::2]))
            _features.append(self.get_PPVs(
                C[:, 1-_padding1::2, padding:-padding], bias_this_dilation[1-_padding1::2]))

        return torch.cat(_features, dim=1)

    def fit(self, X, chunksize=None):
        num_samples = X.shape[0]
        if chunksize is None:
            chunksize = min(num_samples, self.num_dilations * self.num_kernels)
        else: 
            chunksize = min(num_samples, chunksize)
        idxs = np.random.choice(num_samples, chunksize, False)
        self.fitting = True
        if isinstance(X, np.ndarray): 
            self(torch.from_numpy(X[idxs]).to(self.kernels.device))
        else:
            self(X[idxs].to(self.kernels.device))
        self.fitting = False

    def get_PPVs(self, C, bias):
        C = C.unsqueeze(-1)
        bias = bias.view(1, bias.shape[0], 1, bias.shape[1])
        a = (C > bias).float().mean(2).flatten(1)
        if self.add_lsaz:
            dif = (C - bias)
            b = (F.relu(dif).sum(2) /
                 torch.clamp_min(torch.abs(dif).sum(2), 1e-8)).flatten(1)
            return torch.cat((a, b), dim=1)
        else:
            return a

    def set_dilations(self, input_length):
        num_features_per_kernel = self.num_features // self.num_kernels
        true_max_dilations_per_kernel = min(
            num_features_per_kernel, self.max_dilations_per_kernel)
        multiplier = num_features_per_kernel / true_max_dilations_per_kernel
        max_exponent = np.log2((input_length - 1) / (self.kernel_size - 1))
        dilations, num_features_per_dilation = \
            np.unique(np.logspace(0, max_exponent, true_max_dilations_per_kernel, base=2).astype(
                np.int32), return_counts=True)
        num_features_per_dilation = (
            num_features_per_dilation * multiplier).astype(np.int32)
        remainder = num_features_per_kernel - num_features_per_dilation.sum()
        i = 0
        while remainder > 0:
            num_features_per_dilation[i] += 1
            remainder -= 1
            i = (i + 1) % len(num_features_per_dilation)
        self.num_features_per_dilation = num_features_per_dilation
        self.num_dilations = len(dilations)
        self.dilations = dilations
        self.padding = []
        for i, dilation in enumerate(dilations):
            self.padding.append((((self.kernel_size - 1) * dilation) // 2))

    def set_channel_combinations(self, num_channels, max_num_channels):
        num_combinations = self.num_kernels * self.num_dilations
        if max_num_channels:
            max_num_channels = min(num_channels, max_num_channels)
        else:
            max_num_channels = num_channels
        max_exponent_channels = np.log2(max_num_channels + 1)
        num_channels_per_combination = (
            2 ** np.random.uniform(0, max_exponent_channels, num_combinations)).astype(np.int32)
        self.num_channels_per_combination = num_channels_per_combination
        channel_combinations = torch.zeros(
            (1, num_channels, num_combinations, 1))
        for i in range(num_combinations):
            channel_combinations[:, np.random.choice(
                num_channels, num_channels_per_combination[i], False), i] = 1
        channel_combinations = torch.split(
            channel_combinations, self.num_kernels, 2)  # split by dilation
        for i, channel_combination in enumerate(channel_combinations):
            self.register_buffer(
                f'channel_combinations_{i}', channel_combination)  # per dilation

    def get_quantiles(self, n):
        return torch.tensor([(_ * ((np.sqrt(5) + 1) / 2)) % 1 for _ in range(1, n + 1)]).float()

    def get_bias(self, C, num_features_this_dilation):
        isp = torch.randint(C.shape[0], (self.num_kernels,))
        samples = C[isp].diagonal().T
        biases = torch.quantile(samples, self.get_quantiles(
            num_features_this_dilation).to(C.device), dim=1).T
        return biases

    def get_indices(self, kernel_size, max_num_kernels):
        num_pos_values = math.ceil(kernel_size / 3)
        num_neg_values = kernel_size - num_pos_values
        pos_values = num_neg_values / num_pos_values
        if kernel_size > 9:
            random_kernels = [np.sort(np.random.choice(kernel_size, num_pos_values, False)).reshape(
                1, -1) for _ in range(max_num_kernels)]
            indices = torch.from_numpy(
                np.concatenate(random_kernels, 0)).unsqueeze(1)
        else:
            indices = torch.LongTensor(list(itertools.combinations(
                np.arange(kernel_size), num_pos_values))).unsqueeze(1)
            if max_num_kernels and len(indices) > max_num_kernels:
                indices = indices[np.sort(np.random.choice(
                    len(indices), max_num_kernels, False))]
        return indices, pos_values

# %% ../../nbs/057_models.MINIROCKETPlus_Pytorch.ipynb 5
class Flatten(nn.Module):
    def forward(self, x): return x.view(x.size(0), -1)
    

class MiniRocketPlus(nn.Sequential):

    def __init__(self, c_in, c_out, seq_len, num_features=10_000, max_dilations_per_kernel=32, kernel_size=9, max_num_channels=None, max_num_kernels=84,
                 bn=True, fc_dropout=0, add_lsaz=False, custom_head=None, zero_init=True):

        # Backbone
        backbone = MiniRocketFeaturesPlus(c_in, seq_len, num_features=num_features, max_dilations_per_kernel=max_dilations_per_kernel,
                                          kernel_size=kernel_size, max_num_channels=max_num_channels, max_num_kernels=max_num_kernels,
                                          add_lsaz=add_lsaz)
        num_features = backbone.num_features * (1 + add_lsaz)

        # Head
        self.head_nf = num_features
        if custom_head is not None: 
            if isinstance(custom_head, nn.Module): head = custom_head
            head = custom_head(self.head_nf, c_out, 1)
        else:
            layers = [Flatten()]
            if bn:
                layers += [nn.BatchNorm1d(num_features)]
            if fc_dropout:
                layers += [nn.Dropout(fc_dropout)]
            linear = nn.Linear(num_features, c_out)
            if zero_init:
                nn.init.constant_(linear.weight.data, 0)
                nn.init.constant_(linear.bias.data, 0)
            layers += [linear]
            head = nn.Sequential(*layers)

        super().__init__(OrderedDict([('backbone', backbone), ('head', head)]))

# %% ../../nbs/057_models.MINIROCKETPlus_Pytorch.ipynb 6
def get_minirocket_features(o, model, chunksize=1024, use_cuda=None, to_np=False):
    """Function used to split a large dataset into chunks, avoiding OOM error."""
    use = torch.cuda.is_available() if use_cuda is None else use_cuda
    device = torch.device(torch.cuda.current_device()
                          ) if use else torch.device('cpu')
    model = model.to(device)
    if isinstance(o, np.ndarray):
        o = torch.from_numpy(o).to(device)
    _features = []
    for oi in torch.split(o, chunksize):
        _features.append(model(oi))
    features = torch.cat(_features).unsqueeze(-1)
    if to_np:
        return features.cpu().numpy()
    else:
        return features

# %% ../../nbs/057_models.MINIROCKETPlus_Pytorch.ipynb 7
class MiniRocketHead(nn.Sequential):
    def __init__(self, c_in, c_out, seq_len=1, bn=True, fc_dropout=0.):
        layers = [nn.Flatten()]
        if bn:
            layers += [nn.BatchNorm1d(c_in)]
        if fc_dropout:
            layers += [nn.Dropout(fc_dropout)]
        linear = nn.Linear(c_in, c_out)
        nn.init.constant_(linear.weight.data, 0)
        nn.init.constant_(linear.bias.data, 0)
        layers += [linear]
        head = nn.Sequential(*layers)
        super().__init__(OrderedDict(
            [('backbone', nn.Sequential()), ('head', head)]))

# %% ../../nbs/057_models.MINIROCKETPlus_Pytorch.ipynb 15
class InceptionRocketFeaturesPlus(nn.Module):
    fitting = False

    def __init__(self, c_in, seq_len, num_features=10_000, max_dilations_per_kernel=32, kernel_sizes=np.arange(3, 10, 2),
                 max_num_channels=None, max_num_kernels=84, add_lsaz=True, same_n_feats_per_ks=False):

        super().__init__()

        self.minirocketfeatures = nn.ModuleList()
        kernel_sizes = [ks for ks in kernel_sizes if ks < seq_len]
        self.kernel_sizes, self.max_num_kernels = kernel_sizes, max_num_kernels
        if same_n_feats_per_ks:
            num_features_per_kernel_size = [num_features // len(kernel_sizes)] * len(kernel_sizes)
        else:
            num_features_per_kernel_size = self._get_n_feat_per_ks(num_features)

        self.num_features = 0
        for kernel_size, num_features_this_kernel_size in zip(kernel_sizes, num_features_per_kernel_size):
            self.minirocketfeatures.append(MiniRocketFeaturesPlus(c_in, seq_len, num_features=num_features_this_kernel_size,
                                                                  max_dilations_per_kernel=max_dilations_per_kernel,
                                                                  kernel_size=kernel_size,
                                                                  max_num_channels=max_num_channels,
                                                                  max_num_kernels=min(
                                                                      max_num_kernels, num_features_this_kernel_size),
                                                                  add_lsaz=add_lsaz))
            self.num_features += self.minirocketfeatures[-1].num_features * (1 + add_lsaz)

    def fit(self, X, chunksize=None):
        for m in self.minirocketfeatures:
            m.fit(X, chunksize=chunksize)

    def forward(self, x):
        features = []
        for m in self.minirocketfeatures:
            features.append(m(x))
        return torch.cat(features, dim=1)

    def _get_n_comb(self, kernel_size):
        if kernel_size > 9: return self.max_num_kernels
        return np.min([self.max_num_kernels, len(list(itertools.combinations(np.arange(kernel_size),  math.ceil(kernel_size / 3))))])

    def _get_n_feat_per_ks(self, num_features):
        combs = np.array([self._get_n_comb(ks) for ks in self.kernel_sizes])
        num_features_per_kernel = num_features // np.sum(combs)
        num_features_per_kernel_size = num_features_per_kernel * combs
        return num_features_per_kernel_size

# %% ../../nbs/057_models.MINIROCKETPlus_Pytorch.ipynb 16
class InceptionRocketPlus(nn.Sequential):

    def __init__(self, c_in, c_out, seq_len, num_features=10_000, max_dilations_per_kernel=32, kernel_sizes=[3, 5, 7, 9],
                 max_num_channels=None, max_num_kernels=84, same_n_feats_per_ks=False, add_lsaz=False, bn=True, fc_dropout=0, custom_head=None, zero_init=True):

        # Backbone
        backbone = InceptionRocketFeaturesPlus(c_in, seq_len, num_features=num_features, max_dilations_per_kernel=max_dilations_per_kernel,
                                               kernel_sizes=kernel_sizes, max_num_channels=max_num_channels, max_num_kernels=max_num_kernels,
                                               same_n_feats_per_ks=same_n_feats_per_ks, add_lsaz=add_lsaz)
        num_features = backbone.num_features

        # Head
        self.head_nf = num_features
        if custom_head is not None: 
            if isinstance(custom_head, nn.Module): head = custom_head
            head = custom_head(self.head_nf, c_out, 1)
        else:
            layers = [Flatten()]
            if bn:
                layers += [nn.BatchNorm1d(num_features)]
            if fc_dropout:
                layers += [nn.Dropout(fc_dropout)]
            linear = nn.Linear(num_features, c_out)
            if zero_init:
                nn.init.constant_(linear.weight.data, 0)
                nn.init.constant_(linear.bias.data, 0)
            layers += [linear]
            head = nn.Sequential(*layers)

        super().__init__(OrderedDict([('backbone', backbone), ('head', head)]))
