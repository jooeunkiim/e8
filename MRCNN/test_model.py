from MRCNN import *
import json
dic = json.load(open("dic.json","r"))
label_map = json.load(open("labels.json", "r"))
decode = {}
for k, v in label_map.items():
    decode[v] = k

import numpy as np
import torch
import utils
from sklearn.metrics import average_precision_score, confusion_matrix

class MyModel(Model):
    def test(self, dataset):
        testloader = DataLoader(dataset = dataset, batch_size=self.batch_size, shuffle=False, num_workers=8, collate_fn=collate_fn)
        evaluate(self.model, dataset.images, 1, testloader, device=self.device)
def getTimestamp():
    import time, datetime
    timezone = 60*60*9 # seconds * minutes * utc + 9
    utc_timestamp = int(time.time() + timezone)
    date = datetime.datetime.fromtimestamp(utc_timestamp).strftime('%Y-%m-%d %
H:%M:%S')
    return utc_timestamp
def evaluate(model, image_names, epoch, data_loader, device):
    device = torch.device('cuda:0') if torch.cuda.is_available() else torch.device('cpu')    
    model.eval()
    metric_logger = utils.MetricLogger(delimiter="  ")
    header = 'Test:'

    logs = {"start":getTimestamp()}
    maskIOUs = {}
    IOUs = {}
    APs = {}
    accs = {}
    for batch_idx, (images, targets) in enumerate(metric_logger.log_every(data_loader, 100, header)):
        images = list(img.to(device) for img in images)
        preds = model(images)
        images_names = [image_names[j] for j in range(batch_idx * 8, (batch_idx+1) * 8) if j in image_names]
        #print(images_names)
        for i, image in enumerate(images):
            pred = preds[i]
            #print(pred.keys())
            boxes = pred['boxes'].detach().cpu()
            labels = pred['labels'].detach().cpu()
            scores = pred['scores'].detach().cpu()
            masks = pred['masks'].detach().cpu()
            image_id = images_names[i]
            #image_id = pred['image_id'].detach().cpu()

            if len(labels) == 0: # if no label, nothing to evaluate	
                continue	

            if image_id in logs:
                pass
            else:
                logs[image_id] = {}

            target = targets[i]
            gt_boxes = target['boxes']
            gt_labels = target['labels']
            gt_masks = target['masks']
            gt_label = gt_labels[0].item()
            class_name = decode[gt_label]
            if class_name in logs[image_id]:
                pass
            else:
                logs[image_id][class_name] = {}
                logs[image_id][class_name]["gt_bbox"] = []
                logs[image_id][class_name]['gt_label'] = []
                logs[image_id][class_name]['label'] = []
                logs[image_id][class_name]['bbox'] = []
                logs[image_id][class_name]['conf'] = []
            for label in gt_labels:
                logs[image_id][class_name]['gt_label'].append(decode[label.item()])
            
            for box in gt_boxes:
                logs[image_id][class_name]["gt_bbox"].append(box.tolist())
            
            pred_result = {}
            for j, label in enumerate(labels):
                label = label.item()
                logs[image_id][class_name]['label'].append(decode[label])
                logs[image_id][class_name]['bbox'].append(boxes[j].tolist())
                logs[image_id][class_name]['conf'].append(float(scores[j]))

                if label in pred_result:
                    pred_result[label]['scores'].append(float(scores[j]))
                    pred_result[label]['boxes'].append(boxes[j])
                    pred_result[label]['masks'].append(masks[j])
                else:
                    pred_result[label]={'scores':[float(scores[j])], 'boxes':[boxes[j]], 'masks':[masks[j]]}
        
            for label, output in pred_result.items():
                N = len(output['scores'])
                temp_boxes = torch.zeros((N, 4))                
                temp_masks = torch.zeros((N, 480, 360), dtype=torch.bool)

                for k, box in enumerate(output['boxes']):
                    temp_boxes[k, :] = box
                for k, mask in enumerate(output['masks']):
                    temp_masks[k, :, :] = mask.bool()

                pred_result[label]['boxes'] = temp_boxes
                pred_result[label]['masks'] = temp_masks
                
            for j, (label, output) in enumerate(pred_result.items()):
                if j in logs[image_id][class_name]:
                    pass
                else:
                    logs[image_id][class_name][j] = {}

                temp_boxes = [gt_box for gt_box, gt_label in zip(gt_boxes, gt_labels) if label == gt_label]
                if not temp_boxes:
                    continue
                
                gt_label_boxes = torch.zeros((len(temp_boxes), 4))
                for k, box in enumerate(temp_boxes):
                    gt_label_boxes[k, :] = box

                box_iou = torchvision.ops.box_iou(output['boxes'], gt_label_boxes)

                box_iou_d1 = torch.max(box_iou, dim=1)
                pred_classes = []
                 
                for temp_iou in box_iou_d1.values:
                    #for temp_iou in iou:
                    temp_iou = float(temp_iou)
                    if temp_iou > 0.3:
                        pred_classes.append(True)
                        logs[image_id][class_name][j]["IOU"] = temp_iou
                        if label in IOUs:
                            IOUs[label].append(temp_iou)
                        else:
                            IOUs[label] = [temp_iou]

                    else:
                        pred_classes.append(False)

                AP = average_precision_score(pred_classes, output['scores'])
                if not np.isnan(AP):
                    logs[image_id][class_name][j]["AP"] = AP
                    if label in APs:
                        APs[label].append(AP)
                    else:
                        APs[label] = [AP]

                if not pred_classes:
                    acc = 0
                else:
                    acc = sum([int(correct) for correct in pred_classes])/len(pred_classes)

                if label in accs:
                    accs[label].append(acc)
                else:
                    accs[label] = [acc]

                
                temp_masks = [gt_mask for gt_mask, gt_label in zip(gt_masks, gt_labels) if label == gt_label]
                
                for mask in temp_masks:
                    mask = mask.bool().numpy()
                    for gt_mask in output['masks'].numpy():
                        intersection = np.logical_and(mask, gt_mask)
                        union = np.logical_or(mask, gt_mask)

                        iou_score = np.sum(intersection) / np.sum(union)
                        if iou_score > 0.2:
                            if label in maskIOUs:
                                maskIOUs[label].append(iou_score)
                           
                            else:
                                maskIOUs[label] = [iou_score]
        #if batch_idx == 0:
        #    print(logs)
    logs["end"] = getTimestamp()
    mean_maskIOU = {decode[int(k)]:np.mean(v) for k, v in maskIOUs.items()}
    mIOU = {decode[int(k)]:np.mean(v) for k, v in IOUs.items()}
    mAP = {decode[int(k)]:np.mean(v) for k, v in APs.items()}
    meanAcc = {decode[int(k)]:np.mean(v) for k, v in accs.items()}
    
    metrics = {"mIOU": mIOU, "mAP": mAP, "meanAcc":meanAcc, "mean_maskIOU":mean_maskIOU}
    import json
    with open(f"metrics_{epoch}.json", "w") as f:
        json.dump(metrics, f)
    del metrics
    
    with open(f"detailed_metrics.json", "w") as f:
        json.dump(logs, f, ensure_ascii=False)
    
    # gather the stats from all processes
    metric_logger.synchronize_between_processes()

import argparse
parser = argparse.ArgumentParser(description='test')
parser.add_argument('--data', default="mrcnn_data.pt", type=str, help="dataset.pt filename")
parser.add_argument('--model', default="mrcnn_model_75.pt", type=str, help="mrcnn_model.pt filename")
args = parser.parse_args()

device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')     
dataset = CustomDataset("/dataset", args.data)
#dataset.labels = {i:dataset.labels[i] for i in range(120)}
#dataset.images = {i:dataset.images[i] for i in range(120)}
myModel = MyModel(num_classes=dataset.num_classes, device = device, model_name = args.model, batch_size=8, parallel=False) # if there is no ckpt to load, pass model_name=None 
myModel.test(dataset)
