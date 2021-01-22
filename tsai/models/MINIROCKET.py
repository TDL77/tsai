# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/111b_models.MINIROCKET.ipynb (unless otherwise specified).

__all__ = ['MINIROCKET', 'get_minirocket_features', 'MiniRocketClassifier', 'MiniRocketRegressor']

# Cell
from ..imports import *
from ..data.external import *
from .layers import *

# Cell
from sktime.transformations.panel.rocket._minirocket import _fit as minirocket_fit
from sktime.transformations.panel.rocket._minirocket import _transform as minirocket_transform
from sktime.transformations.panel.rocket._minirocket_multivariate import _fit_multi as minirocket_fit_multi
from sktime.transformations.panel.rocket._minirocket_multivariate import _transform_multi as minirocket_transform_multi

# Cell
from sklearn.pipeline import make_pipeline
from sktime.transformations.panel.rocket import MiniRocketMultivariate
from sklearn.linear_model import RidgeCV, RidgeClassifierCV
from sklearn.metrics import mean_squared_error, make_scorer

# Cell
# This is an unofficial MINIROCKET implementation in Pytorch developed by Ignacio Oguiza - timeseriesAI@gmail.com based on:
# Dempster, A., Schmidt, D. F., & Webb, G. I. (2020). MINIROCKET: A Very Fast (Almost) Deterministic Transform for Time Series Classification.
# arXiv preprint arXiv:2012.08791.
# Official repo: https://github.com/angus924/minirocket

class MINIROCKET(nn.Module):
    def __init__(self, c_in, c_out, seq_len=1, fc_dropout=0., custom_head=None, **kwargs):
        """
        MINIROCKET implementation where features are previously calculated.
        Args:
            c_in: number of features per sample. For 10_000 kernels iw will be 9996.
            c_out: number of classes.
            seq_len: For MINIROCKET this is always 1 as features are previously calculated. Included for compatibility.
            fc_dropout: indicates whether dropout should be added to the last fully connected layer
            custom_head: used when a different type of head needs to be applied
        """
        super().__init__()
        self.head_nf = c_in
        if custom_head is not None:
            self.head = custom_head(c_in, c_out, seq_len, fc_dropout=fc_dropout, **kwargs)
        else:
            layers = []
            if fc_dropout: layers += [nn.Dropout(fc_dropout)]
            linear = nn.Linear(c_in, c_out)
            nn.init.constant_(linear.weight.data, 0)
            nn.init.constant_(linear.bias.data, 0)
            layers += [linear]
            self.head = nn.Sequential(*layers)

    def forward(self, x):
        return self.head(x.squeeze(-1))

# Cell
def get_minirocket_features(X, num_features=10_000, max_dilations_per_kernel=32, on_disk=True, path='./data/MINIROCKET', fname='X_tfm',
                            features_last=True, random_state=None):
    """
    Args:
        features_last: set to True when using features with MiniRocketClassifier or MiniRocketRegressor. Set to False when using MINIROCKET (Pytorch).
    """
    if X.dtype == 'float64': X = X.astype('float32')
    if X.shape[1] == 1:
        rocket_params = minirocket_fit(X[:, 0], num_features=num_features, max_dilations_per_kernel=max_dilations_per_kernel, seed=random_state)
        X_tfm = minirocket_transform(X[:, 0], rocket_params)
    else:
        rocket_params = minirocket_fit_multi(X, num_features=num_features, max_dilations_per_kernel=max_dilations_per_kernel, seed=random_state)
        X_tfm = minirocket_transform_multi(X, rocket_params)
    del X
    gc.collect()
    X_tfm = X_tfm[:, np.newaxis] if features_last else X_tfm[..., np.newaxis]
    if on_disk:
        full_fname = Path(path)/f'{fname}.npy'
        if not os.path.exists(Path(path)): os.makedirs(Path(path))
        np.save(full_fname, X_tfm)
        del X_tfm
        X_tfm = np.load(full_fname, mmap_mode='r+')
    return X_tfm

# Cell
class MiniRocketClassifier(sklearn.pipeline.Pipeline):
    def __init__(self, num_features=10000, max_dilations_per_kernel=32, random_state=None,
                 alphas=np.logspace(-3, 3, 13), normalize=True, memory=None, verbose=False, scoring=None, class_weight=None, **kwargs):
        """
        MiniRocketClassifier is recommended for up to 10k time series.
        For a larger dataset, you can use MINIROCKET (in Pytorch).
        scoring = None --> defaults to accuracy.
        """
        self.steps = [('minirocketmultivariate', MiniRocketMultivariate(num_features=num_features,
                                                                        max_dilations_per_kernel=max_dilations_per_kernel,
                                                                        random_state=random_state)),
                      ('ridgeclassifiercv', RidgeClassifierCV(alphas=alphas, normalize=normalize, scoring=scoring, class_weight=class_weight, **kwargs))]
        self.num_features, self.max_dilations_per_kernel, self.random_state = num_features, max_dilations_per_kernel, random_state
        self.alphas, self.normalize, self.scoring, self.class_weight, self.kwargs = alphas, normalize, scoring, class_weight, kwargs
        self.memory = memory
        self.verbose = verbose
        self._validate_steps()

# Cell
class MiniRocketRegressor(sklearn.pipeline.Pipeline):
    def __init__(self, num_features=10000, max_dilations_per_kernel=32, random_state=None,
                 alphas=np.logspace(-3, 3, 13), *, normalize=True, memory=None, verbose=False, scoring=None, **kwargs):
        """
        MiniRocketRegressor is recommended for up to 10k time series.
        For a larger dataset, you can use MINIROCKET (in Pytorch).
        scoring = None --> defaults to r2.
        """
        self.steps = [('minirocketmultivariate', MiniRocketMultivariate(num_features=num_features,
                                                                        max_dilations_per_kernel=max_dilations_per_kernel,
                                                                        random_state=random_state)),
                      ('ridgecv', RidgeCV(alphas=alphas, normalize=normalize, scoring=scoring, **kwargs))]
        self.num_features, self.max_dilations_per_kernel, self.random_state = num_features, max_dilations_per_kernel, random_state
        self.alphas, self.normalize, self.scoring, self.kwargs = alphas, normalize, scoring, kwargs
        self.memory = memory
        self.verbose = verbose
        self._validate_steps()