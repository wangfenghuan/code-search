use std::collections::HashMap;

/// 订单状态枚举
#[derive(Debug, PartialEq)]
pub enum OrderStatus {
    Pending,
    Paid,
    Cancelled,
}

/// 订单领域实体
pub struct Order {
    pub id: String,
    pub amount: f64,
    pub status: OrderStatus,
}

/// 订单服务处理器 Trait
pub trait OrderProcessor {
    fn process(&self, order: &Order) -> bool;
}

/// 订单业务服务实现
pub struct OrderService {
    orders: HashMap<String, Order>,
}

impl OrderService {
    /// 构造新的订单服务实例
    pub fn new() -> Self {
        Self {
            orders: HashMap::new(),
        }
    }

    /// 获取指定订单详情接口
    #[get("/api/v1/orders")]
    pub async fn get_order(&self, order_id: &str) -> Option<&Order> {
        self.orders.get(order_id)
    }

    /// 创建并结算新订单
    #[post("/api/v1/orders")]
    pub async fn create_order(&mut self, id: String, amount: f64) -> OrderStatus {
        let order = Order {
            id: id.clone(),
            amount,
            status: OrderStatus::Paid,
        };
        self.orders.insert(id, order);
        notify_order_created(&amount);
        OrderStatus::Paid
    }
}

/// 独立通知辅助函数
pub fn notify_order_created(amount: &f64) -> bool {
    println!("Order created with amount: {}", amount);
    true
}
