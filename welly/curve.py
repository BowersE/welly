"""
Defines log curves.

:copyright: 2021 Agile Scientific
:license: Apache 2.0
"""
from __future__ import division

import numpy as np
from scipy.interpolate import interp1d

import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.patches import PathPatch
import warnings


from . import utils


class CurveError(Exception):
    """
    Generic error class.
    """
    pass


class Curve(np.ndarray):
    """
    A fancy ndarray. Gives some utility functions, plotting, etc, for curve
    data.
    """
    def __new__(cls, data, basis=None, params=None):
        """
        I am just following the numpy guide for subclassing ndarray...
        """
        obj = np.asarray(data).view(cls).copy()

        params = params or {}

        for k, v in params.items():
            setattr(obj, k, v)

        if basis is not None:
            if basis[0] > basis[1]:
                basis = np.flipud(basis)
            setattr(obj, 'start', basis[0])
            setattr(obj, 'step', basis[1]-basis[0])

        return obj

    def __array_finalize__(self, obj):
        """
        I am just following the numpy guide for subclassing ndarray...
        """
        if obj is None:
            return

        if obj.size == 1:
            return float(obj)

        self.start = getattr(obj, 'start', 0)
        self.step = getattr(obj, 'step', 1)
        self.mnemonic = getattr(obj, 'mnemonic', None)
        self.units = getattr(obj, 'units', None)
        self.run = getattr(obj, 'run', 0)
        self.null = getattr(obj, 'null', -999.25)
        self.service_company = getattr(obj, 'service_company', None)
        self.date = getattr(obj, 'date', None)
        self.code = getattr(obj, 'code', None)
        self.basis_units = getattr(obj, 'basis_units', None)

    def __getitem__(self, items):
        """
        Update the basis when a Curve is sliced.
        """
        newarr = self.copy()
        if isinstance(items, slice):
            if (items.start is not None) and (items.start > 0):
                newarr.start = newarr.basis.copy()[items.start]
            if items.step is not None:
                newarr.step = newarr.step * items.step

        return np.ndarray.__getitem__(newarr, items)

    def __copy__(self):
        cls = self.__class__
        result = cls.__new__(cls)
        result.__dict__.update(self.__dict__)
        return result

    def _repr_html_(self):
        """
        Jupyter Notebook magic repr function.
        """
        if self.size < 10:
            return np.ndarray.__repr__(self)
        attribs = self.__dict__.copy()

        # Header.
        row1 = '<tr><th style="text-align:center;" colspan="2">{} [{{}}]</th></tr>'
        rows = row1.format(attribs.pop('mnemonic'))
        rows = rows.format(attribs.pop('units', '&ndash;'))
        row2 = '<tr><td style="text-align:center;" colspan="2">{:.4f} : {:.4f} : {:.4f}</td></tr>'
        rows += row2.format(attribs.pop('start'), self.stop, attribs.pop('step'))

        # Curve attributes.
        s = '<tr><td><strong>{k}</strong></td><td>{v}</td></tr>'
        for k, v in attribs.items():
            rows += s.format(k=k, v=v)

        # Curve stats.
        rows += '<tr><th style="border-top: 2px solid #000; text-align:center;" colspan="2"><strong>Stats</strong></th></tr>'
        stats = self.get_stats()
        s = '<tr><td><strong>samples (NaNs)</strong></td><td>{samples} ({nulls})</td></tr>'
        s += '<tr><td><strong><sub>min</sub> mean <sup>max</sup></strong></td>'
        s += '<td><sub>{min:.2f}</sub> {mean:.3f} <sup>{max:.2f}</sup></td></tr>'
        rows += s.format(**stats)

        # Curve preview.
        s = '<tr><th style="border-top: 2px solid #000;">Depth</th><th style="border-top: 2px solid #000;">Value</th></tr>'
        rows += s.format(self.start, self[0])
        s = '<tr><td>{:.4f}</td><td>{:.4f}</td></tr>'
        for depth, value in zip(self.basis[:3], self[:3]):
            rows += s.format(depth, value)
        rows += '<tr><td>⋮</td><td>⋮</td></tr>'
        for depth, value in zip(self.basis[-3:], self[-3:]):
            rows += s.format(depth, value)

        # Footer.
        # ...

        # End.
        html = '<table>{}</table>'.format(rows)
        return html

    @property
    def values(self):
        return np.array(self)

    @property
    def stop(self):
        """
        The stop depth. Computed on the fly from the start,
        the step, and the length of the curve.
        """
        return self.start + (self.shape[0] - 1) * self.step

    @property
    def basis(self):
        """
        The depth or time basis of the curve's points. Computed
        on the fly from the start, stop and step.

        Returns
            ndarray. The array, the same length as the curve.
        """
        return np.linspace(self.start, self.stop, self.shape[0], endpoint=True)

    def describe(self):
        """
        Return basic statistics about the curve.
        """
        stats = {}
        stats['samples'] = self.shape[0]
        stats['nulls'] = self[np.isnan(self)].shape[0]
        stats['mean'] = float(np.nanmean(self.real))
        stats['min'] = float(np.nanmin(self.real))
        stats['max'] = float(np.nanmax(self.real))
        return stats

    get_stats = describe

    @classmethod
    def from_lasio_curve(cls, curve,
                         depth=None,
                         basis=None,
                         start=None,
                         stop=None,
                         step=0.1524,
                         run=-1,
                         null=-999.25,
                         service_company=None,
                         date=None,
                         basis_units=None):
        """
        Makes a curve object from a lasio curve object and either a depth
        basis or start and step information.

        Args:
            curve (ndarray)
            depth (ndarray)
            basis (ndarray)
            start (float)
            stop (float)
            step (float): default: 0.1524
            run (int): default: -1
            null (float): default: -999.25
            service_company (str): Optional.
            date (str): Optional.
            basis_units (str): the units of the basis.

        Returns:
            Curve. An instance of the class.
        """
        data = curve.data
        unit = curve.unit

        # See if we have uneven sampling.
        if depth is not None:
            d = np.diff(depth)
            if not np.allclose(d - np.mean(d), np.zeros_like(d)):
                # Sampling is uneven.
                m = "Irregular sampling in depth is not supported. "
                m += "Interpolating to regular basis."
                warnings.warn(m)
                step = np.nanmedian(d)
                start, stop = depth[0], depth[-1]+0.00001  # adjustment
                basis = np.arange(start, stop, step)
                data = np.interp(basis, depth, data)
            else:
                step = np.nanmedian(d)
                start = depth[0]

        # Carry on with easier situations.
        if start is None:
            if basis is not None:
                start = basis[0]
                step = basis[1] - basis[0]
            else:
                raise CurveError("You must provide a basis or a start depth.")

        if step == 0:
            if stop is None:
                raise CurveError("You must provide a step or a stop depth.")
            else:
                step = (stop - start) / (curve.data.shape[0] - 1)

        # Interpolate into this.

        params = {}
        params['mnemonic'] = curve.mnemonic
        params['description'] = curve.descr
        params['start'] = start
        params['step'] = step
        params['units'] = unit
        params['run'] = run
        params['null'] = null
        params['service_company'] = service_company
        params['date'] = date
        params['code'] = curve.API_code
        params['basis_units'] = basis_units

        return cls(data, params=params)

    def get_alias(self, alias):
        """
        Given a mnemonic, get the alias name(s) it falls under. If there aren't
        any, you get an empty list.
        """
        alias = alias or {}
        return [k for k, v in alias.items() if self.mnemonic in v]

    def plot_2d(self, ax=None,
                width=None,
                aspect=60,
                cmap=None,
                curve=False,
                ticks=(1, 10),
                return_fig=False,
                **kwargs,
                ):
        """
        Plot a 2D curve.

        Args:
            ax (ax): A matplotlib axis.
            width (int): The width of the image.
            aspect (int): The aspect ratio (not quantitative at all).
            cmap (str): The colourmap to use.
            curve (bool): Whether to plot the curve as well.
            ticks (tuple): The tick interval on the y-axis.
            return_fig (bool): whether to return the matplotlib figure.
                Default False.

        Returns:
            ax. If you passed in an ax, otherwise None.
        """
        # Set up the figure.
        if ax is None:
            fig = plt.figure(figsize=(2, 10))
            ax = fig.add_subplot(111)
            return_ax = False
        else:
            return_ax = True

        # Set up the data.
        cmap = cmap or 'viridis'
        default = int(self.shape[0] / aspect)
        if self.ndim == 1:
            a = np.expand_dims(self, axis=1)
            a = np.repeat(a, width or default, axis=1)
        elif self.ndim == 2:
            a = self[:, :width] if width < self.shape[1] else self
        elif self.ndim == 3:
            if 2 < self.shape[-1] < 5:
                # Interpret as RGB or RGBA.
                a = utils.normalize(np.copy(self))
                cmap = None  # Actually doesn't matter.
            else:
                # Take first slice.
                a = self[:, :width, 0] if width < self.shape[1] else self[..., 0]
        else:
            raise NotImplementedError("Can only handle up to 3 dimensions.")

        # At this point, a is either a 2D array, or a 2D (rgb) array.
        extent = [0, width or default, self.stop, self.start]
        im = ax.imshow(a, cmap=cmap, extent=extent, aspect='auto')

        if curve:
            paths = ax.fill_betweenx(self.basis, self, np.nanmin(self),
                                     facecolor='none',
                                     **kwargs,
                                     )

            # Make the 'fill' mask and clip the background image with it.
            patch = PathPatch(paths._paths[0], visible=False)
            ax.add_artist(patch)
            im.set_clip_path(patch)

        ax.set_xticks([])

        # Rely on interval order.
        lower, upper = self.stop, self.start
        rng = abs(upper - lower)

        ax.set_ylim([lower, upper])

        # Make sure ticks is a tuple.
        try:
            ticks = tuple(ticks)
        except TypeError:
            ticks = (1, ticks)

        # Avoid MAXTICKS error.
        while rng/ticks[0] > 250:
            mi, ma = 10*ticks[0], ticks[1]
            if ma <= mi:
                ma = 10 * mi
            ticks = (mi, ma)

        # Carry on plotting...
        minorLocator = mpl.ticker.MultipleLocator(ticks[0])
        ax.yaxis.set_minor_locator(minorLocator)

        majorLocator = mpl.ticker.MultipleLocator(ticks[1])
        majorFormatter = mpl.ticker.FormatStrFormatter('%d')
        ax.yaxis.set_major_locator(majorLocator)
        ax.yaxis.set_major_formatter(majorFormatter)

        ax.yaxis.set_ticks_position('left')
        ax.get_yaxis().set_tick_params(which='both', direction='out')

        if return_ax:
            return ax
        elif return_fig:
            plt.tight_layout()
            return fig
        else:
            return None

    def plot(self, ax=None, legend=None, return_fig=False, alias=None, **kwargs):
        """
        Plot a curve.

        Args:
            ax (ax): A matplotlib axis.
            legend (striplog.legend): A legend. Optional. Should contain kwargs for ax.set().
            return_fig (bool): whether to return the matplotlib figure.
                Default False.
            kwargs: Arguments for ``ax.plot()``

        Returns:
            ax. If you passed in an ax, otherwise None.
        """
        if ax is None:
            fig = plt.figure(figsize=(2, 10))
            ax = fig.add_subplot(111)
            return_ax = False
        else:
            return_ax = True

        d = None

        if legend is not None:
            try:
                d = legend.get_decor(self)
            except:
                pass

        if d is not None:
            kwargs['color'] = d.colour
            kwargs['lw'] = getattr(d, 'lineweight', None) or getattr(d, 'lw', 1)
            kwargs['ls'] = getattr(d, 'linestyle', None) or getattr(d, 'ls', '-')

        ax.plot(self, self.basis, **kwargs)

        if d is not None:
            # Attempt to get axis parameters from decor.
            axkwargs = {}

            xlim = getattr(d, 'xlim', None)
            if xlim is not None:
                axkwargs['xlim'] = list(map(float, xlim.split(',')))

            xticks = getattr(d, 'xticks', None)
            if xticks is not None:
                axkwargs['xticks'] = list(map(float, xticks.split(',')))

            xscale = getattr(d, 'xscale', None)
            if xscale is not None:
                axkwargs['xscale'] = xscale

            ax.set(**axkwargs)

        ax.set_title(self.mnemonic)  # no longer needed
        ax.set_xlabel(self.units)

        if False:  # labeltop of axes?
            ax.xaxis.tick_top()

        if True:  # rotate x-tick labels
            labels = ax.get_xticklabels()
            for label in labels:
                label.set_rotation(90)

        ax.set_ylim([self.stop, self.start])
        ax.grid('on', color='k', alpha=0.33, lw=0.33, linestyle='-')

        if return_ax:
            return ax
        elif return_fig:
            return fig
        else:
            return None

    def extrapolate(self):
        """
        From ``bruges``

        Extrapolate up and down an array from the first and last non-NaN samples.

        E.g. Continue the first and last non-NaN values of a log up and down.
        """
        return utils.extrapolate(self)

    def top_and_tail(self):
        return utils.top_and_tail(self)

    def interpolate(self):
        """
        Interpolate across any missing zones.

        TODO
        Allow spline interpolation.
        """
        nans, x = utils.nan_idx(self)
        self[nans] = np.interp(x(nans), x(~nans), self[~nans])
        return self

    def interpolate_where(self, condition):
        """
        Remove values according to some condition, then interpolate across
        the gap(s) created.
        """
        raise NotImplementedError()

    def to_basis_like(self, basis):
        """
        Make a new curve in a new basis, given an existing one. Wraps
        ``to_basis()``.

        Pass in a curve or the basis of a curve.

        Args:
            basis (ndarray): A basis, but can also be a Curve instance.

        Returns:
            Curve. The current instance in the new basis.
        """
        try:  # To treat as a curve.
            curve = basis
            basis = curve.basis
            undefined = curve.null
        except:
            undefined = None

        return self.to_basis(basis=basis,
                             undefined=undefined)

    def to_basis(self, basis=None,
                 start=None,
                 stop=None,
                 step=None,
                 undefined=None,
                 interp_kind='linear',
                 ):
        """
        Make a new curve in a new basis, given a basis, or a new start, step,
        and/or stop. You only need to set the parameters you want to change.
        If the new extents go beyond the current extents, the curve is padded
        with the ``undefined`` parameter.

        Args:
            basis (ndarray): The basis to compute values for. You can provide
                a basis, or start, stop, step, or a combination of the two.
            start (float): The start position to use. Overrides the start of
                the basis, if one is provided.
            stop (float): The end position to use. Overrides the end of
                the basis, if one is provided.
            step (float): The step to use. Overrides the step in the basis, if
                one is provided.
            undefined (float): The value to use outside the curve's range. By
                default, np.nan is used.
            interp_kind (str): The kind of interpolation to use to compute the
                new positions, default is 'linear'. Options are ‘linear’,
                ‘nearest’, ‘nearest-up’, ‘zero’, ‘slinear’, ‘quadratic’,
                ‘cubic’, ‘previous’, or ‘next’. See scipy.interpolate.interp1d.

        Returns:
            Curve. The current instance in the new basis.
        """
        if basis is None:
            new_start = self.start if start is None else start
            new_stop = self.stop if stop is None else stop
            new_step = self.step if step is None else step
        else:
            new_start = basis[0] if start is None else start
            new_stop = basis[-1] if stop is None else stop
            new_step = (basis[1] - basis[0]) if step is None else step

        steps = np.ceil((new_stop - new_start) / new_step)
        basis = np.linspace(new_start, new_stop, int(steps) + 1, endpoint=True)

        if undefined is None:
            undefined = np.nan
        else:
            undefined = undefined

        interp = interp1d(self.basis, self,
                          kind=interp_kind,
                          bounds_error=False,
                          fill_value=undefined)

        data = interp(basis)

        params = self.__dict__.copy()
        params['step'] = float(new_step)
        params['start'] = float(new_start)

        return Curve(data, params=params)

    def _read_at(self, d,
                 interpolation='linear',
                 index=False,
                 ):
        """
        Private function. Implements read_at() for a single depth.

        Args:
            d (float)
            interpolation (str)
            index(bool)
            return_basis (bool)

        Returns:
            float
        """
        method = {'linear': utils.linear,
                  'none': None}

        i, d = utils.find_previous(self.basis,
                                   d,
                                   index=True,
                                   return_distance=True)

        if index:
            return i
        else:
            return method[interpolation](self[i], self[i+1], d)

    def read_at(self, d, **kwargs):
        """
        Read the log at a specific depth or an array of depths.

        Args:
            d (float or array-like)
            interpolation (str)
            index(bool)
            return_basis (bool)

        Returns:
            float or ndarray.
        """
        try:
            return np.array([self._read_at(depth, **kwargs) for depth in d])
        except:
            return self._read_at(d, **kwargs)

    def quality(self, tests, alias=None):
        """
        Run a series of tests and return the corresponding results.

        Args:
            tests (list): a list of functions.
            alias (dict): a dictionary mapping mnemonics to lists of mnemonics.

        Returns:
            list. The results. Stick to booleans (True = pass) or ints.
        """
        # Gather the test s.
        # First, anything called 'all', 'All', or 'ALL'.
        # Second, anything with the name of the curve we're in now.
        # Third, anything that the alias list has for this curve.
        # (This requires a reverse look-up so it's a bit messy.)
        this_tests =\
            tests.get('each', [])+tests.get('Each', [])+tests.get('EACH', [])\
            + tests.get(self.mnemonic, [])\
            + utils.flatten_list([tests.get(a) for a in self.get_alias(alias=alias)])
        this_tests = filter(None, this_tests)

        # If we explicitly set zero tests for a particular key, then this
        # overrides the 'all' and 'alias' tests.
        if not tests.get(self.mnemonic, 1):
            this_tests = []

        return {test.__name__: test(self) for test in this_tests}

    def qflag(self, tests, alias=None):
        """
        Run a test and return the corresponding results on a sample-by-sample
        basis.

        Args:
            tests (list): a list of functions.
            alias (dict): a dictionary mapping mnemonics to lists of mnemonics.

        Returns:
            list. The results. Stick to booleans (True = pass) or ints.
        """
        # Gather the tests.
        # First, anything called 'all', 'All', or 'ALL'.
        # Second, anything with the name of the curve we're in now.
        # Third, anything that the alias list has for this curve.
        # (This requires a reverse look-up so it's a bit messy.)
        this_tests =\
            tests.get('each', [])+tests.get('Each', [])+tests.get('EACH', [])\
            + tests.get(self.mnemonic, [])\
            + utils.flatten_list([tests.get(a) for a in self.get_alias(alias=alias)])
        this_tests = filter(None, this_tests)

        return {test.__name__: test(self) for test in this_tests}

    def qflags(self, tests, alias=None):
        """
        Run a series of tests and return the corresponding results.

        Args:
            tests (list): a list of functions.
            alias (dict): a dictionary mapping mnemonics to lists of mnemonics.

        Returns:
            list. The results. Stick to booleans (True = pass) or ints.
        """
        # Gather the tests.
        # First, anything called 'all', 'All', or 'ALL'.
        # Second, anything with the name of the curve we're in now.
        # Third, anything that the alias list has for this curve.
        # (This requires a reverse look-up so it's a bit messy.)
        this_tests =\
            tests.get('each', [])+tests.get('Each', [])+tests.get('EACH', [])\
            + tests.get(self.mnemonic, [])\
            + utils.flatten_list([tests.get(a) for a in self.get_alias(alias=alias)])
        this_tests = filter(None, this_tests)

        return {test.__name__: test(self) for test in this_tests}

    def quality_score(self, tests, alias=None):
        """
        Run a series of tests and return the normalized score.
            1.0:   Passed all tests.
            (0-1): Passed a fraction of tests.
            0.0:   Passed no tests.
            -1.0:  Took no tests.

        Args:
            tests (list): a list of functions.
            alias (dict): a dictionary mapping mnemonics to lists of mnemonics.

        Returns:
            float. The fraction of tests passed, or -1 for 'took no tests'.
        """
        results = self.quality(tests, alias=alias).values()
        if results:
            return sum(results) / len(results)
        return -1

    def block(self,
              cutoffs=None,
              values=None,
              n_bins=0,
              right=False,
              function=None):
        """
        Block a log based on number of bins, or on cutoffs.

        Args:
            cutoffs (array): the values at which to create the blocks. Pass
                a single number, or an array-like of multiple values. If you
                don't pass `cutoffs`, you should pass `n_bins` (below).
            values (array): the values to map to. Defaults to [0, 1, 2,...].
                There must be one more value than you have `cutoffs` (e.g.
                2 cutoffs will create 3 zones, each of which needs a value).
            n_bins (int): The number of discrete values to use in the blocked
                log. Only used if you don't pass `cutoffs`.
            right (bool): Indicating whether the intervals include the right
                or the left bin edge. Default behavior is `right==False`
                indicating that the interval does not include the right edge. 
            function (function): transform the log with a reducing function,
                such as np.mean.

        Returns:
            Curve.
        """
        # We'll return a copy.
        params = self.__dict__.copy()

        if (values is not None) and (cutoffs is None):
            cutoffs = values[1:]

        if (cutoffs is None) and (n_bins == 0):
            cutoffs = np.mean(self)

        if (n_bins != 0) and (cutoffs is None):
            mi, ma = np.amin(self), np.amax(self)
            cutoffs = np.linspace(mi, ma, n_bins+1)
            cutoffs = cutoffs[:-1]

        try:  # To use cutoff as a list.
            data = np.digitize(self, cutoffs, right)
        except ValueError:  # It's just a number.
            data = np.digitize(self, [cutoffs], right)

        if (function is None) and (values is None):
            return Curve(data, params=params)

        data = data.astype(float)

        # Set the function for reducing.
        f = function or utils.null

        # Find the tops of the 'zones'.
        tops, vals = utils.find_edges(data)

        # End of array trick... adding this should remove the
        # need for the marked lines below. But it doesn't.
        # np.append(tops, None)
        # np.append(vals, None)

        if values is None:
            # Transform each segment in turn, then deal with the last segment.
            for top, base in zip(tops[:-1], tops[1:]):
                data[top:base] = f(np.copy(self[top:base]))
            data[base:] = f(np.copy(self[base:]))  # See above
        else:
            for top, base, val in zip(tops[:-1], tops[1:], vals[:-1]):
                data[top:base] = values[int(val)]
            data[base:] = values[int(vals[-1])]  # See above

        return Curve(data, params=params)

    def _rolling_window(self, window_length, func1d, step=1, return_rolled=False):
        """
        Private function. Smoother for other smoothing/conditioning functions.

        Args:
            window_length (int): the window length.
            func1d (function): a function that takes a 1D array and returns a
                scalar.
            step (int): if you want to skip samples in the shifted versions.
                Don't use this for smoothing, you will get strange results.

        Returns:
            ndarray: the resulting array.
        """
        # Force odd.
        if window_length % 2 == 0:
            window_length += 1

        shape = self.shape[:-1] + (self.shape[-1], window_length)
        strides = self.strides + (step*self.strides[-1],)
        data = np.nan_to_num(self)
        data = np.pad(data, int(step*window_length//2), mode='edge')
        rolled = np.lib.stride_tricks.as_strided(data,
                                                 shape=shape,
                                                 strides=strides)
        result = np.apply_along_axis(func1d, -1, rolled)
        result[np.isnan(self)] = np.nan

        if return_rolled:
            return result, rolled
        else:
            return result

    def despike(self, window_length=33, samples=True, z=2):
        """
        Args:
            window (int): window length in samples. Default 33 (or 5 m for
                most curves sampled at 0.1524 m intervals).
            samples (bool): window length is in samples. Use False for a window
                length given in metres.
            z (float): Z score

        Returns:
            Curve.
        """
        window_length //= 1 if samples else self.step
        z *= np.nanstd(self)  # Transform to curve's units
        curve_sm = self._rolling_window(window_length, np.median)
        spikes = np.where(np.nan_to_num(self - curve_sm) > z)[0]
        spukes = np.where(np.nan_to_num(curve_sm - self) > z)[0]
        out = np.copy(self)
        params = self.__dict__.copy()
        out[spikes] = curve_sm[spikes] + z
        out[spukes] = curve_sm[spukes] - z
        return Curve(out, params=params)

    def apply(self, window_length, samples=True, func1d=None):
        """
        Runs any kind of function over a window.

        Args:
            window_length (int): the window length. Required.
            samples (bool): window length is in samples. Use False for a window
                length given in metres.
            func1d (function): a function that takes a 1D array and returns a
                scalar. Default: ``np.mean()``.

        Returns:
            Curve.
        """
        window_length /= 1 if samples else self.step
        if func1d is None:
            func1d = np.mean
        params = self.__dict__.copy()
        out = self._rolling_window(int(window_length), func1d)
        return Curve(out, params=params)

    smooth = apply

    def plot_kde(self,
                 ax=None,
                 amax=None,
                 amin=None,
                 label=None,
                 return_fig=False):
        """
        Plot a KDE for the curve. Very nice summary of KDEs:
        https://jakevdp.github.io/blog/2013/12/01/kernel-density-estimation/

        Args:
            ax (axis): Optional matplotlib (MPL) axis to plot into. Returned.
            amax (float): Optional max value to permit.
            amin (float): Optional min value to permit.
            label (string): What to put on the y-axis. Defaults to curve name.
            return_fig (bool): If you want to return the MPL figure object.

        Returns:
            None, axis, figure: depending on what you ask for.
        """
        from scipy.stats import gaussian_kde

        if ax is None:
            fig = plt.figure()
            ax = fig.add_subplot(111)
            return_ax = False
        else:
            return_ax = True

        a = self[~np.isnan(self)]

        # Find values for common axis to exclude outliers.
        if amax is None:
            amax = np.percentile(a, 99)
        if amin is None:
            amin = np.percentile(a,  1)

        x = a[np.abs(a - 0.5 * (amax + amin)) < 0.5 * (amax - amin)]
        x_grid = np.linspace(amin, amax, 100)

        kde = gaussian_kde(x)
        std_a = kde.evaluate(x_grid)

        img = np.array([std_a]) / np.max([std_a])
        extent = [amin, amax, 0, 1]
        ax.imshow(img, aspect='auto', cmap='viridis', extent=extent)
        ax.set_yticklabels([])
        ax.set_ylabel(label or self.mnemonic)

        if return_ax:
            return ax
        elif return_fig:
            return fig
        else:
            return None
