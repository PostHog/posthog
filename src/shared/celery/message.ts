export class Message {
    private _decode: Record<string, any> | null = null

    // public deliveryInfo: object;
    // public deliveryTag: string;
    constructor(
        readonly body: Buffer,
        readonly contentType: string,
        readonly contentEncoding: string,
        readonly properties: Record<string, any>,
        readonly headers: Record<string, any>
    ) {}

    public decode(): Record<string, any> {
        if (!this._decode) {
            // now only support application/json, utf-8
            this._decode = JSON.parse(this.body.toString('utf-8'))
        }
        return this._decode as Record<string, any>
    }
}
