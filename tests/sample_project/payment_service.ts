/**
 * 跨境电商在线支付网关服务
 */

export interface PaymentRequest {
    orderId: string;
    amount: number;
    currency: string;
}

export class PaymentGateway {
    private apiKey: string;

    constructor(apiKey: string = "secret_payment_key") {
        this.apiKey = apiKey;
    }

    /**
     * 发起在线支付交易：请求第三方支付渠道生成收银台 URL
     */
    async processPayment(req: PaymentRequest): Promise<{ success: boolean; payUrl: string }> {
        if (!req.orderId || req.amount <= 0) {
            throw new Error("无效的订单支付参数");
        }
        return {
            success: true,
            payUrl: `https://pay.example.com/checkout?order=${req.orderId}`,
        };
    }

    /**
     * 处理订单退款业务逻辑：原路退还用户支付资金
     */
    async refundOrder(orderId: string, refundAmount: number): Promise<boolean> {
        // 模拟退款操作
        return true;
    }
}
