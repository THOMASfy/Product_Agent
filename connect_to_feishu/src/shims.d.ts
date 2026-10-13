declare module "word-extractor" {
  interface Document {
    getBody(): string
    getFootnotes(): string
    getEndnotes(): string
    getHeaders(): string
    getTextboxes(): string
  }
  class WordExtractor {
    constructor(options?: Record<string, unknown>)
    extract(source: string | Buffer): Promise<Document>
  }
  export = WordExtractor
}
