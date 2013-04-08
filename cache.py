#! /usr/bin/env python

'''
Research code

Jason Yosinski
'''

import ipdb as pdb
import hashlib
import marshal
import os
from datetime import datetime
import time
from numpy import *
import cPickle as pickle
import types
import inspect
import gzip



# Directory to use for caching
globalCacheDir     = os.path.join(os.path.expanduser("~"), '.pycache')    # symlink to local disk if desired

globalCacheVerbose = 2                  # 0: print nothing. 1: Print info about hits or misses. 2: print filenames. 3: print hash steps
globalDisableCache = False              # Set to True to disable all caching



__all__ = ['globalCacheDir', 'globalCacheVerbose', 'globalDisableCache', 'memoize', 'cached']



class PersistentHasher(object):
    '''Hashes, persistently and consistenly. Suports only two methods:
    update and hexdigest. Supports numpy arrays and dicts.'''

    def __init__(self, verbose = None):
        self.verbose = verbose if verbose is not None else globalCacheVerbose
        self.counter = 0
        self.hashAlg = hashlib.sha1()
        if self.verbose >= 3:
            self._printStatus()
        self.salt = '3.14159265358979323'


    def update(self, obj, level = 0):
        '''A smarter, more persistent verison of hashlib.update'''
        if isinstance(obj, types.BuiltinFunctionType):
            # Function name is sufficient for builtin functions.
            # Built in functions do not have func_code, but their code
            # is unlikely to change anyway.
            self.hashAlg.update(obj.__name__)
        elif isinstance(obj, types.FunctionType):
            # For user defined functions, hash the function name and
            # function code itself (a bit overconservative)
            self.hashAlg.update(obj.__name__)
            self.hashAlg.update(marshal.dumps(obj.func_code))
        elif type(obj) is ndarray:
            # can update directly with numpy arrays
            self.hashAlg.update(self.salt + 'numpy.ndarray')
            self.hashAlg.update(obj)
        elif type(obj) is dict:
            self.hashAlg.update(self.salt + 'dict')
            for key,val in sorted(obj.items()):
                self.hashAlg.update(str(hash(key)))
                self.update(val, level = level + 1)  # recursive call
        elif inspect.isclass(obj):
            raise Exception('Hashing whole classes not supported yet (have not implemented reliable way to hash all methods)')
        else:
            # Just try to hash it
            try:
                self.hashAlg.update(str(hash(obj)))
                #print '  updating with obj hash', str(hash(obj))
            except TypeError:
                if type(obj) is tuple or type(obj) is list:
                    # Tuples are only hashable if all their components are.
                    self.hashAlg.update(self.salt + ('tuple' if type(obj) is tuple else 'list'))
                    for item in obj:
                        self.update(item, level = level + 1)  # recursive call
                else:
                    print 'UNSUPPORTED TYPE: FIX THIS!'
                    print type(obj)
                    print obj
                    print 'UNSUPPORTED TYPE: FIX THIS!'
                    pdb.set_trace()

        self.counter += 1
        if self.verbose >= 3:
            self._printStatus(level, repr(type(obj)))


    def hexdigest(self):
        return self.hashAlg.hexdigest()


    def _printStatus(self, level = 0, typeStr = None):
        st = '%sAfter %3d objects hashed, hash is %s' % ('    ' * level, self.counter, self.hexdigest()[:4])
        if typeStr is not None:
            st += ' (latest %s)' % typeStr
        print st



def memoize(function):
    '''Decorator to memoize function'''

    if globalDisableCache:

        def wrapper(*args, **kwargs):
            if globalCacheVerbose >= 1:
                print ' -> cache.py: cache disabled by globalDisableCache'
            return function(*args, **kwargs)

    else:

        def wrapper(*args, **kwargs):
            startHashWall = time.time()

            # Hash the function, its args, and its kwargs
            hasher = PersistentHasher()
            hasher.update(function)
            hasher.update(args)
            hasher.update(kwargs)

            # Check cache for previous result
            functionName = function.__name__    # a little more reliable than func_name
            digest = hasher.hexdigest()

            cacheFilename    = '%s.%s.pkl.gz' % (digest[:16], functionName)
            # get a unique filename that does not affect any random number generators
            cacheTmpFilename = '.%s-%06d.tmp' % (cacheFilename, datetime.now().microsecond)
            cachePath    = os.path.join(globalCacheDir, cacheFilename[:2], cacheFilename)
            cacheTmpPath = os.path.join(globalCacheDir, cacheFilename[:2], cacheTmpFilename)
            elapsedHashWall = time.time() - startHashWall

            try:
                start = time.time()
                (stats,result) = loadFromPklGz(cachePath)
                elapsedWall = time.time() - start
                if globalCacheVerbose >= 1:
                    print (' -> cache.py: %s: cache hit (%.04fs hash overhead, %.04fs to load, saved %.04fs)'
                           % (functionName, elapsedHashWall, elapsedWall, stats['timeWall'] - elapsedWall))
                    if globalCacheVerbose >= 2:
                        print '   -> loaded %s' % cachePath
            except IOError:
                startWall = time.time()
                startCPU  = time.clock()
                result = function(*args, **kwargs)
                elapsedWall = time.time() - startWall
                elapsedCPU  = time.clock() - startCPU
                    
                stats = {'functionName': functionName,
                         'timeWall': elapsedWall,
                         'timeCPU': elapsedCPU,
                         'saveDate': datetime.now(),
                         }

                startSave = time.time()
                mkdir_p(os.path.dirname(cachePath))
                saveToFile(cacheTmpPath, (stats,result), quiet = True)
                os.rename(cacheTmpPath, cachePath)
                if globalCacheVerbose >= 1:
                    print (' -> cache.py: %s: cache miss (%.04fs hash overhead, %.04fs to save, %.04fs to compute)'
                           % (functionName, elapsedHashWall, time.time() - startSave, elapsedWall))
                    if globalCacheVerbose >= 2:
                        print '   -> saved to %s' % cachePath

            return result

    return wrapper



def cached(function, *args, **kwargs):
    '''Return cached answer or compute and cache.'''

    memoizedFunction = memoize(function)
    return memoizedFunction(*args, **kwargs)



def saveToFile(filename, obj, quiet = False):
    ff = gzip.open(filename, 'wb')
    pickle.dump(obj, ff, protocol = -1)
    if not quiet:
        print 'saved to', filename
    ff.close()



def loadFromPklGz(filename):
    with gzip.open(filename, 'rb') as ff:
        ret = pickle.load(ff)
    return ret



def mkdir_p(path):
    '''Behaves like `mkdir -P` on Linux.
    From: http://stackoverflow.com/questions/600268/mkdir-p-functionality-in-python'''
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise



def invNoncached(mat, times = 1.0):
    return times * linalg.inv(mat)



@memoize
def invCached(mat, times = 1.0):
    return times * linalg.inv(mat)



def main():
    random.seed(0)
    a = random.rand(500,500)
    #print 'a is\n', a
    
    #ainv = invNoncached(a)
    #ainv = invCached(a)
    #ainv = linalg.inv(a)

    print 'computing ainv * 1.0'
    invCached(a, times = 1.0)
    print 'computing ainv * 2.0'
    invCached(a, 2.0)
    print 'computing cached(linalg.inv, a)'
    cached(linalg.inv, a)



if __name__ == '__main__':
    main()
