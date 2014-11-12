import logging

logger = logging.getLogger('updater')

import itertools
from multiprocessing import Pool

import numpy as np
import pandas as pd

from base import UpdaterBase
import zyconsensus_sql as zysql

"""
The updater class for collection 'zyconsensus'
"""

def worker(args):
    sid, df = args
    actual = df.iloc[0]
    if actual['consensus_type'] != 0:
        return sid, None
    summary = {'growth': actual['growth']}
    for i, _dname in itertools.product(range(-1, 3), zysql._dnames2):
        try:
            summary[_dname+'_'+str(i)] = df[_dname].iloc[i+1]
        except:
            summary[_dname+'_'+str(i)] = np.nan
    return sid, summary


class ZYConsensusUpdater(UpdaterBase):

    def __init__(self, threads=16, cutoff='08:30:00', timeout=60):
        UpdaterBase.__init__(self, timeout)
        self.threads = threads
        self.cutoff = cutoff

    def pre_update(self):
        self.connect_zyyx()
        self.__dict__.update({
            'dates': self.db.dates.distinct('date'),
            'collection': self.db.zyconsensus,
            })

    def pro_update(self):
        return

        logger.debug('Ensuring index date_1_dname_1 on collection %s', self.collection.name)
        self.collection.ensure_index([('date', 1), ('dname', 1)],
                unique=True, dropDups=True, background=True)
        logger.debug('Ensuring index dname_1_date_1 on collection %s', self.collection.name)
        self.collection.ensure_index([('dname', 1), ('date', 1)],
                unique=True, dropDups=True, background=True)

    def update(self, date):
        prev_date = self.dates[self.dates.index(date)-1]
        self.update_target_price(date, prev_date)
        self.update_consensus(date, prev_date)

    def update_target_price(self, date, prev_date):
        CMD = zysql.CMD1.format(date=date, prev_date=prev_date, cutoff=self.cutoff)
        logger.debug('Executing command:\n%s', CMD)
        self.cursor.execute(CMD)
        df = pd.DataFrame(list(self.cursor))
        if len(df) == 0:
            logger.warning('No records found for %s@dname=target_price on %s', self.collection.name, prev_date)
            return

        df.columns = ['sid'] + zysql.dnames1
        df.index = df.sid

        for dname in zysql.dnames1:
            key = {'dname': dname, 'date': prev_date}
            self.collection.update(key, {'$set': {'dvalue': df[dname].dropna().to_dict()}}, upsert=True)
        logger.info('UPSERT documents for %d sids into (c: [%s@dname=target_price]) of (d: [%s]) on %s', len(df), self.collection.name, self.db.name, prev_date)

    def update_consensus(self, date, prev_date):
        CMD = zysql.CMD2.format(date=date, prev_date=prev_date, cutoff=self.cutoff)
        logger.debug('Executing command:\n%s', CMD)
        self.cursor.execute(CMD)
        df = pd.DataFrame(list(self.cursor))
        if len(df) == 0:
            logger.warning('No records found for %s@dname=consensus on %s', self.collection.name, prev_date)
            return

        df.columns = ['sid', 'consensus_type', 'forecast_year', 'growth'] + zysql._dnames2
        grouped = df.groupby('sid')

        pool = Pool(self.threads)
        res = pool.imap(worker, grouped, self.threads)

        df = pd.DataFrame({sid: summary for sid, summary in res}).T.dropna(how='all')
        for dname in zysql.dnames2:
            key = {'dname': dname, 'date': prev_date}
            self.collection.update(key, {'$set': {'dvalue': df[dname].dropna().to_dict()}}, upsert=True)
        logger.info('UPSERT documents for %d sids into (c: [%s@dname=consensus]) of (d: [%s]) on %s', len(df), self.collection.name, self.db.name, prev_date)


if __name__ == '__main__':
    zy = ZYConsensusUpdater()
    zy.run()