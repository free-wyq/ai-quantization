"""策略基类"""

from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    """所有交易策略的基类"""

    def __init__(self, name: str = "BaseStrategy"):
        self.name = name

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        根据行情数据生成交易信号

        Args:
            df: 包含 OHLCV 数据的 DataFrame

        Returns:
            添加了 signal 列的 DataFrame
            signal: 1=买入, -1=卖出, 0=持有
        """
        pass

    def __repr__(self):
        return f"<Strategy: {self.name}>"
