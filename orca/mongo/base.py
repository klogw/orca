"""
.. moduleauthor:: Li, Wang <wangziqi@foreseefund.com>
"""

import abc

import pandas as pd
from pandas.tseries.index import DatetimeIndex

import logbook
logbook.set_datetime_format('local')

from orca import (
        DATES,
        SIDS,
        )
from orca.utils import dateutil

class FetcherBase(object):
    """Base class for mongo fetchers.

    :param boolean datetime_index: Whether to use DatetimeIndex or list of date strings. Default: False
    :param boolean reindex: Whether to use full sids as columns in DataFrame. Default: False
    :param boolean date_check: Whethter to check if passed date-related parameters are valid. Default: False
    :param int delay: Delay fetched data in :py:meth:`~orca.mongo.base.FetcherBase.fetch_history`. Default: 1

    .. note::

       This is a base class and should not be used directly.
    """

    __metaclass__ = abc.ABCMeta

    LOGGER_NAME = 'mongo'

    def __init__(self, datetime_index=False, reindex=False, date_check=False, delay=1):
        self.logger = logbook.Logger(FetcherBase.LOGGER_NAME)
        self.datetime_index = datetime_index
        self.reindex = reindex
        self.date_check = date_check
        self.delay = delay

    def debug(self, msg):
        """Logs a message with level DEBUG on the alpha logger."""
        self.logger.debug(msg)

    def info(self, msg):
        """Logs a message with level INFO on the alpha logger."""
        self.logger.info(msg)

    def warning(self, msg):
        """Logs a message with level WARNING on the alpha logger."""
        self.logger.warning(msg)

    def error(self, msg):
        """Logs a message with level ERROR on the alpha logger."""
        self.logger.error(msg)

    def critical(self, msg):
        """Logs a message with level CRITICAL on the alpha logger."""
        self.logger.critical(msg)

    @staticmethod
    def format(df, datetime_index, reindex):
        if datetime_index:
            df.index = pd.to_datetime(df.index)
        if reindex:
            return df.reindex(columns=SIDS, copy=False)
        return df

    @abc.abstractmethod
    def fetch(self, dname, startdate, enddate=None, backdays=0, **kwargs):
        """Override(**mandatory**) to fetch data within two endpoints.

        :param str dname: Name of the data
        :param startdate: The **left** (may not be the actual) endpoint
        :type startdate: str, int
        :param enddate: The **right** endpoint. Default: None, defaults to the last date
        :type enddate: str, int, None
        :param int backdays: This will shift (left/right: >/< 0) the left endpoint. Default: 0
        :returns: DataFrame
        :raises: NotImplementedError

        .. seealso:: :py:func:`orca.mongo.dateutil.cut_window`
        """
        raise NotImplementedError

    @abc.abstractmethod
    def fetch_window(self, dname, window, **kwargs):
        """Override(**mandatory**) to fetch data for consecutive trading days.

        :param str dname: Name of the data
        :param list window: List of consecutive trading dates
        :returns: DataFrame
        :raises: NotImplementedError
        """
        raise NotImplementedError

    @abc.abstractmethod
    def fetch_history(self, dname, date, backdays, **kwargs):
        """Override(**mandatory**) to fetch data with respect to a base point.

        :param str dname: Name of the data
        :param date: The date(with additional tweaks specified in ``kwargs`` and ``self.delay``) as a base point
        :type date: str, int
        :param int backdays: Number of days to look back w.r.t. the base point
        :returns: DataFrame
        :raises: NotImplementedError
        """
        raise NotImplementedError

    @abc.abstractmethod
    def fetch_daily(self, dname, date, offset=0, **kwargs):
        """Override(**mandatory**) to fetch data series on a certain date.

        :param str dname: Name of the data
        :param date: The base point
        :type date: str, int
        :param int offset: The offset w.r.t. the ``date``. The actual fetched date is calculated from ``date`` and ``offset``. Default: 0
        :returns: Series
        :raises: NotImplementedError
        """
        raise NotImplementedError

    @abc.abstractmethod
    def fetch_dates(self, dname, dates, offset=0, **kwargs):
        """Override(**mandatory**) to fetch data series on a certain date.

        :param str dname: Name of the data
        :param dates: The base points
        :param int offset: The offset w.r.t. the ``date``. The actual fetched date is calculated from date in ``dates`` and ``offset``. Default: 0
        :returns: Series
        :raises: NotImplementedError
        """
        raise NotImplementedError


class RecordFetcher(FetcherBase):
    """Base class to fetch time-stamped records as DataFrame.

    .. note::

       This is a base class and should not be used directly.
    """

    def __init__(self, **kwargs):
        super(RecordFetcher, self).__init__(**kwargs)

    def fetch(self, startdate=None, enddate=None, backdays=0, dnames=[], **kwargs):
        """Use :py:meth:`fetch_window` behind the scene."""
        date_check = kwargs.get('date_check', self.date_check)
        if startdate is None:
            startdate = DATES[0]
        window = dateutil.cut_window(
                DATES,
                dateutil.compliment_datestring(str(startdate), -1, date_check),
                dateutil.compliment_datestring(str(enddate), 1, date_check) if enddate is not None else None,
                backdays=backdays)
        return self.fetch_window(window, dnames=dnames, **kwargs)

    def fetch_window(self, window, dnames=[], **kwargs):
        query = {'date': {'$gte': window[0], '$lte': window[-1]}}
        proj = {'_id': 0}
        if dnames:
            proj['date'], proj['sid'] = 1, 1
            for dname in dnames:
                proj[dname] = 1
        cursor = self.collection.find(query, proj)
        df = pd.DataFrame(list(cursor))
        del cursor
        return df

    def fetch_history(self, date, backdays, **kwargs):
        """Use :py:meth:`fetch_window` behind the scene."""
        date_check = kwargs.get('date_check', self.date_check)
        delay = kwargs.get('delay', self.delay)

        date = dateutil.compliment_datestring(str(date), -1, date_check)
        di, date = dateutil.parse_date(DATES, date, -1)
        di -= delay
        window = DATES[di-backdays+1: di+1]
        return self.fetch_window(window, **kwargs)

    def fetch_daily(self, date, offset=0, **kwargs):
        """Use :py:meth:`fetch_window` behind the scene."""
        return self.fetch_history(date, 1, delay=offset, **kwargs)

    def fetch_dates(self, dates, rshift=0, lshift=0, **kwargs):
        """Use :py:meth:`fetch_window` behind the scene."""
        dates_str = dateutil.to_datestr(dates)
        res, is_df = {}, False
        for dt, date in zip(dates, dates_str):
            di, date = dateutil.parse_date(DATES, date, -1)
            if di-lshift < 0 or di+rshift+1 > len(DATES):
                continue
            if rshift+lshift == 0:
                res[dt] = self.fetch_daily(DATES[di-lshift], **kwargs)
                if isinstance(res[dt], pd.DataFrame):
                    is_df = True
            else:
                res[dt] = self.fetch_window(DATES[di-lshift: di+rshift+1], **kwargs)
        if rshift+lshift == 0:
            res = pd.Panel(res).transpose(1, 2, 0) if is_df else pd.DataFrame(res).T
        return res


class KDayFetcher(FetcherBase):
    """Base class to fetch daily data that can be formatted as DataFrame.

    .. note::

       This is a base class and should not be used directly.
    """

    def __init__(self, **kwargs):
        super(KDayFetcher, self).__init__(**kwargs)

    def fetch(self, dname, startdate, enddate=None, backdays=0, **kwargs):
        """Use :py:meth:`fetch_window` behind the scene."""
        date_check = kwargs.get('date_check', self.date_check)

        window = dateutil.cut_window(
                DATES,
                dateutil.compliment_datestring(str(startdate), -1, date_check),
                dateutil.compliment_datestring(str(enddate), 1, date_check) if enddate is not None else None,
                backdays=backdays)
        return self.fetch_window(dname, window, **kwargs)

    def fetch_window(self, dname, window, **kwargs):
        """Fetch data from a certain collection in MongoDB. For most cases, this is the **only** method that needs
        to be overridden.
        """
        datetime_index = kwargs.get('datetime_index', self.datetime_index)
        reindex = kwargs.get('reindex', self.reindex)

        query = {'dname': dname, 'date': {'$gte': window[0], '$lte': window[-1]}}
        proj = {'_id': 0, 'dvalue': 1, 'date': 1}
        cursor = self.collection.find(query, proj)
        df = pd.DataFrame({row['date']: row['dvalue'] for row in cursor}).T
        del cursor
        return self.format(df, datetime_index, reindex)

    def fetch_history(self, dname, date, backdays, **kwargs):
        """Use :py:meth:`fetch_window` behind the scene."""
        date_check = kwargs.get('date_check', self.date_check)
        delay = kwargs.get('delay', self.delay)

        date = dateutil.compliment_datestring(str(date), -1, date_check)
        di, date = dateutil.parse_date(DATES, date, -1)
        di -= delay
        window = DATES[di-backdays+1: di+1]
        return self.fetch_window(dname, window, **kwargs)

    def fetch_daily(self, dname, date, offset=0, **kwargs):
        """Use :py:meth:`fetch_window` behind the scene."""
        return self.fetch_history(dname, date, 1, delay=offset, **kwargs).iloc[0]

    def fetch_dates(self, dname, dates, rshift=0, lshift=0, **kwargs):
        """Use :py:meth:`fetch_window` behind the scene."""
        dates_str = dateutil.to_datestr(dates)
        res, is_df = {}, False
        for dt, date in zip(dates, dates_str):
            di, date = dateutil.parse_date(DATES, date, -1)
            if di-lshift < 0 or di+rshift+1 > len(DATES):
                continue
            if rshift+lshift == 0:
                res[dt] = self.fetch_daily(dname, DATES[di-lshift], **kwargs)
                if isinstance(res[dt], pd.DataFrame):
                    is_df = True
            else:
                res[dt] = self.fetch_window(dname, DATES[di-lshift: di+rshift+1], **kwargs)
        if rshift+lshift == 0:
            res = pd.Panel(res).transpose(1, 2, 0) if is_df else pd.DataFrame(res).T
        return res


class KMinFetcher(FetcherBase):
    """Base class to fetch minute-bar interval data.

    .. note::

       This is a base class and should not be used directly.
    """

    def __init__(self, **kwargs):
        super(KMinFetcher, self).__init__(**kwargs)

    def fetch(self, dname, times, startdate, enddate=None, backdays=0, **kwargs):
        """Use :py:meth:`fetch_window` behind the scene."""
        date_check = kwargs.get('date_check', self.date_check)

        window = dateutil.cut_window(
                DATES,
                dateutil.compliment_datestring(str(startdate), -1, date_check),
                dateutil.compliment_datestring(str(enddate), 1, date_check) if enddate is not None else None,
                backdays=backdays)
        return self.fetch_window(dname, times, window, **kwargs)

    def fetch_window(self, dname, times, window, as_frame=False, **kwargs):
        """Fetch minute-bar data(specified by time stamps) for a consecutive days.

        :param times: Time stamps to indicate which minute-bars should be fetched. This will affect the returned data type; when it is ``[]``, it defaults to fetch all times
        :type times: str, list
        :param boolean as_frame: Only use this when ``times`` is a list. Default: False
        :returns: DataFrame(if ``type(times)`` is ``str``) or Panel(with ``times`` as the item-axis)
        """
        datetime_index = kwargs.get('datetime_index', self.datetime_index)
        reindex = kwargs.get('reindex', self.reindex)

        query = {'dname': dname,
                 'date': {'$gte': window[0], '$lte': window[-1]},
                 }
        if not times:
            times = self.intervals
        query.update({'time': {'$in': [times] if isinstance(times, str) else times}})
        proj = {'_id': 0, 'dvalue': 1, 'date': 1, 'time': 1}
        cursor = self.collection.find(query, proj)
        dfs = pd.DataFrame({(row['date'], row['time']): row['dvalue'] for row in cursor}).T
        del cursor
        dfs.index.names = ['date', 'time']
        panel = dfs.to_panel().transpose(2, 1, 0)
        if datetime_index:
            panel.major_axis = pd.to_datetime(panel.major_axis)
            if reindex:
                panel = panel.reindex(minor_axis=SIDS, copy=False)
        elif reindex:
            panel = panel.reindex(minor_axis=SIDS)

        if isinstance(times, str):
            return panel[times]
        return self.to_frame(panel) if as_frame else panel

    def fetch_history(self, dname, times, date, backdays, **kwargs):
        """Use :py:meth:`fetch_window` behind the scene."""
        date_check = kwargs.get('date_check', self.date_check)
        delay = kwargs.get('delay', self.delay)

        date = dateutil.compliment_datestring(str(date), -1, date_check)
        di, date = dateutil.parse_date(DATES, date, -1)
        di -= delay
        window = DATES[di-backdays+1: di+1]
        return self.fetch_window(dname, times, window, **kwargs)

    def fetch_daily(self, dname, times, date, offset=0, as_frame=False, **kwargs):
        """Use :py:meth:`fetch_window` behind the scene.

        :returns: Series(if ``type(times)`` is ``str``) or DataFrame(with ``times`` as the columns)
        """
        res = self.fetch_history(dname, times, date, 1, delay=offset, **kwargs)
        if isinstance(times, str):
            return res.iloc[0]
        return res if as_frame else res.major_xs(res.major_axis[0]).T

    @staticmethod
    def to_frame(panel):
        """Transform a time-itemized, date-major_axised Panel into DataFrame with DatetimeIndex."""
        if isinstance(panel.major_axis, DatetimeIndex):
            panel.major_axis = dateutil.to_datestr(panel.major_axis)
        df = panel.transpose(2, 1, 0).to_frame(filter_observations=False)
        df.index = pd.to_datetime(pd.Series(df.index.get_level_values(0)) + ' ' + \
                                  pd.Series(df.index.get_level_values(1)))
        return df

    def generate_dateintervals(self, date, time, num, offset=0):
        """Generate an ordered list of (date, time) tuple."""
        di = DATES.index(date)
        ti = self.intervals.index(time)

        if offset >= 0:
            for i in range(offset):
                date, time = DATES[di], self.intervals[ti]
                if ti == 0:
                    ti = len(self.intervals)
                    di -= 1
                ti -= 1
        else:
            for i in range(-offset):
                date, time = DATES[di], self.intervals[ti]
                if ti == len(self.intervals) - 1:
                    ti = 0
                    di += 1
                ti += 1

        cnt, res = 0, []
        while cnt < num:
            date, time = DATES[di], self.intervals[ti]
            if ti == 0:
                ti = len(self.intervals)
                di -= 1
            ti -= 1
            cnt += 1
            res.append((date, time))
        return res[::-1]

    def fetch_intervals(self, dname, date, time, num=None, offset=0, **kwargs):
        """Return a consecutive interval data
        ``offset`` is to set offset of ``time``; along with ``date``, they determine the ending datetime.
        """
        date_check = kwargs.get('date_check', self.date_check)
        reindex = kwargs.get('reindex', self.reindex)

        date = dateutil.compliment_datestring(str(date), -1, date_check)
        date = dateutil.parse_date(DATES, date, -1)[1]

        dateintervals = self.generate_dateintervals(date, time, num=1 if num is None else num, offset=offset)
        dateindex = pd.to_datetime([dis[0]+' '+dis[1] for dis in dateintervals])
        window = [dis[0] for dis in dateintervals]

        query = {'dname': dname,
                 'date': {'$gte': window[0], '$lte': window[-1]},
                 }
        proj = {'_id': 0, 'dvalue': 1, 'date': 1, 'time': 1}
        cursor = self.collection.find(query, proj)
        df = pd.DataFrame({row['date']+' '+row['time']: row['dvalue'] for row in cursor}).T
        del cursor
        df.index = pd.to_datetime(df.index)
        df = df.ix[dateindex]
        if reindex:
            df = df.reindex(columns=SIDS)
        return df.iloc[0] if num is None else df

    def fetch_dates(self, dname, times, dates, rshift=0, lshift=0, **kwargs):
        """Use :py:meth:`fetch_window` behind the scene."""
        dates_str = dateutil.to_datestr(dates)
        res, is_df = {}, False
        for dt, date in zip(dates, dates_str):
            di, date = dateutil.parse_date(DATES, date, -1)
            if di-lshift < 0 or di+rshift+1 > len(DATES):
                continue
            if rshift+lshift == 0:
                res[dt] = self.fetch_daily(dname, times, DATES[di-lshift], **kwargs)
                if isinstance(res[dt], pd.DataFrame):
                    is_df = True
            else:
                res[dt] = self.fetch_window(dname, times, DATES[di-lshift: di+rshift+1], **kwargs)

        if rshift+lshift == 0:
            res = pd.Panel(res).transpose(1, 2, 0) if is_df else pd.DataFrame(res).T
        return res
