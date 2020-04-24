
from matchpy import *

class Scalar(Symbol):
    pass


class TransformerBase:
    '''
        Base class for all transformers. Implements the various operators >> + * | & 
    '''

    def transform(self, topics_or_res):
        pass

    def __rshift__(self, right):
        # if isinstance(self, ComposedPipeline):
        #      self.models.append(right)
        #      return self
        # if isinstance(right, ComposedPipeline):
        #     right.models.append(self)
        #     return right
        return ComposedPipeline([self, right])

    def __add__(self, right):
        return CombSumTransformer([self, right])

    def __pow__(self, right):
        # if isinstance(self, FeatureUnionPipeline):
        #      self.models.append(right)
        #      return self
        # if isinstance(right, FeatureUnionPipeline):
        #     right.models.append(self)
        #     return right
        return FeatureUnionPipeline([self, right])

    def __mul__(self, rhs):
        assert isinstance(rhs, int) or isinstance(rhs, float)
        return ScalarProductTransformer(self, rhs)

    def __rmul__(self, lhs):
        assert isinstance(lhs, int) or isinstance(lhs, float)
        return ScalarProductTransformer(self, lhs)

    def __or__(self, right):
        return SetUnionTransformer([self, right])

    def __and__(self, right):
        return SetIntersectionTransformer([self, right])

class IdentityTransformer(TransformerBase, Operation):
    arity = Arity.nullary

    def __init__(self):
        super(IdentityTransformer, self).__init__()
    
    def transform(self, topics):
        return topics

# this class is useful for testing. it returns a copy of the same
# dataframe each time transform is called
class UniformTransformer(TransformerBase, Operation):
    arity = Arity.nullary

    def __init__(self, rtr):
        super(UniformTransformer, self).__init__()
        self.rtr = rtr
    
    def transform(self, topics):
        return self.rtr.copy()

class BinaryTransformerBase(TransformerBase,Operation):
    arity = Arity.binary

    def __init__(self, operands):
        super(BinaryTransformerBase, self).__init__(operands=operands)
        self.left = left
        self.right = right

class NAryTransformerBase(TransformerBase,Operation):
    arity = Arity.polyadic

    def __init__(self, operands):
        super(NAryTransformerBase, self).__init__(operands=operands)
        models = operands
        self.models = list( map(lambda x : LambdaPipeline(x) if callable(x) else x, models) )

class SetUnionTransformer(BinaryTransformerBase):
    name = "Union"

    def transform(self, topics):
        res1 = self.left.transform(topics)
        res2 = self.right.transform(topics)
        import pandas as pd
        rtr = pd.concat([res1, res2])
        rtr = rtr.drop_duplicates(subset=["qid", "docno"])
        rtr = rtr.sort_values(by=['qid', 'docno'])
        rtr = rtr.drop(columns=["score"])
        return rtr

class SetIntersectionTransformer(BinaryTransformerBase):
    name = "Intersect"
    
    def transform(self, topics):
        res1 = self.left.transform(topics)
        res2 = self.right.transform(topics)
        # NB: there may be othe other duplicate columns
        rtr = res1.merge(res2, on=["qid", "docno"]).drop(columns=["score_x", "score_y"])
        return rtr

class CombSumTransformer(BinaryTransformerBase):
    name = "Sum"

    def transform(self, topics_and_res):
        res1 = self.left.transform(topics_and_res)
        res2 = self.right.transform(topics_and_res)
        merged = res1.merge(res2, on=["qid", "docno"])
        merged["score"] = merged["score_x"] + merged["score_y"]
        merged = merged.drop(columns=['score_x', 'score_y'])
        return merged

# multiplies the retrieval score by a scalar
class ScalarProductTransformer(TransformerBase):
    arity = Arity.binary
    name = "ScalarProd"

    def __init__(self, transformer, scalar):
        super(ScalarProductTransformer, self).__init__(operands=[Scalar(scalar), transformer])
        self.transformer = transformer
        self.scalar = scalar

    def transform(self, topics_and_res):
        res = self.transformer.transform(topics_and_res)
        res["score"] = self.scalar * res["score"]
        return res

class LambdaPipeline(TransformerBase):
    """
    This class allows pipelines components to be written as functions or lambdas

    :Example:
    >>> #this pipeline would remove all but the first two documents from a result set
    >>> lp = LambdaPipeline(lambda res : res[res["rank"] < 2])

    """

    def __init__(self, lambdaFn):
        super(LambdaPipeline, self).__init__()
        self.fn = lambdaFn

    def transform(self, inputRes):
        fn = self.fn
        return fn(inputRes)

class FeatureUnionPipeline(NAryTransformerBase):
    name = "FUnion"

    def transform(self, inputRes):
        assert "docno" in inputRes.columns or "docid" in inputRes.columns
        
        all_results = []
        for m in self.models:
            results = m.transform(inputRes).rename(columns={"score" : "features"})
            all_results.append( results )
        
        def _reduce_fn(left, right):
            import pandas as pd
            import numpy as np
            rtr = pd.merge(left, right, on=["qid", "docno"])
            rtr["features"] = rtr.apply(lambda row : np.stack([row["features_x"], row["features_y"]]), axis=1)
            rtr.drop(columns=["features_x", "features_y"], inplace=True)
            return rtr
        
        from functools import reduce
        final_DF = reduce(_reduce_fn, all_results)
        final_DF = inputRes.merge(final_DF, on=["qid", "docno"])
        return final_DF

class ComposedPipeline(NAryTransformerBase):
    name = "Compose"
    """ 
    This class allows pipeline components to be chained together using the "then" operator.

    :Example:

    >>> comp = ComposedPipeline([ DPH_br, LambdaPipeline(lambda res : res[res["rank"] < 2])])
    >>> OR
    >>>  # we can even use lambdas as transformers
    >>> comp = ComposedPipeline([DPH_br, lambda res : res[res["rank"] < 2]])
    
    """
    
    def transform(self, topics):
        for m in self.models:
            topics = m.transform(topics)
        return topics